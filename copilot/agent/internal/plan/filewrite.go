package plan

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
	"github.com/dominikramachers/ha-copilot/agent/internal/tools"
)

// ToolFileWrite schreibt eine Textdatei (Stufe 2, immer über den Root-Helfer, mit Sicherungskopie).
const ToolFileWrite = "file_write"

const (
	maxWriteBytes  = 24 * 1024  // Inhalt, den die KI auf einmal schickt
	maxFileBytes   = 100 * 1024 // größte Datei, die bearbeitet wird (Vergleich und Sicherung)
	backupInfix    = ".copilot-bak-"
	keepBackups    = 5
	baseUnreadable = "unreadable"
)

// Diese Pfade werden nie geschrieben (Stufe 3): System, Anmeldung, Start und der Agent selbst.
var (
	writeDenyPrefix = []string{
		"/proc", "/sys", "/dev", "/boot", "/run", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/usr/bin", "/usr/sbin", "/usr/lib",
		"/usr/local/bin", "/usr/local/sbin", "/etc/ssh", "/etc/pam.d", "/etc/security", "/etc/sudoers.d", "/etc/copilot-agent",
		"/var/lib/copilot-agent", "/root", "/etc/systemd/system/copilot-", "/lib/systemd/system/copilot-",
	}
	writeDenyExact = map[string]bool{
		"/etc/passwd": true, "/etc/shadow": true, "/etc/group": true, "/etc/gshadow": true, "/etc/sudoers": true, "/etc/fstab": true,
		"/etc/crypttab": true, "/etc/passwd-": true, "/etc/shadow-": true, "/etc/ld.so.preload": true, "/etc/ld.so.conf": true,
		"/etc/nsswitch.conf": true, "/etc/login.defs": true, "/etc/inittab": true, "/etc/securetty": true,
	}
)

func writeDenied(real string) bool {
	if writeDenyExact[real] || strings.Contains(real, "/.ssh/") || filepath.Base(real) == "authorized_keys" {
		return true
	}
	for _, p := range writeDenyPrefix {
		if real == p || strings.HasPrefix(real, p+"/") || (strings.HasSuffix(p, "-") && strings.HasPrefix(real, p)) {
			return true
		}
	}
	return false
}

func sha(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

// confined öffnet das erlaubte Verzeichnis (aus der lokalen Richtlinie, nie aus der Eingabe), in dem der aufgelöste Pfad liegt, und
// gibt den Rest als relativen Namen zurück. Alle Zugriffe auf bestehende Dateien laufen darüber (os.Root): Sie können das
// Verzeichnis auch durch einen Link oder einen Wettlauf zwischen Prüfung und Zugriff nicht verlassen.
func confined(pol policy.Policy, real string) (*os.Root, string, error) {
	for _, dir := range pol.WritePaths {
		if !strings.HasPrefix(real, dir+"/") {
			continue
		}
		root, err := os.OpenRoot(dir)
		if err != nil {
			return nil, "", err
		}
		return root, strings.TrimPrefix(real, dir+"/"), nil
	}
	return nil, "", errors.New("writing to this path is not allowed")
}

// readConfined liest eine bestehende Datei (soweit der aufrufende Benutzer sie lesen darf): Angaben, Inhalt und Hash.
// Eine nicht lesbare Datei ergibt den Hash baseUnreadable.
func readConfined(pol policy.Policy, real string) (os.FileInfo, string, string, error) {
	root, rel, err := confined(pol, real)
	if err != nil {
		return nil, "", "", err
	}
	defer root.Close()
	info, err := root.Lstat(rel)
	if err != nil {
		return nil, "", "", err
	}
	if !info.Mode().IsRegular() {
		return nil, "", "", errors.New("the path is not a regular file")
	}
	if info.Size() > maxFileBytes {
		return nil, "", "", fmt.Errorf("the file is larger than %d KiB; it is not edited through the AI", maxFileBytes/1024)
	}
	f, err := root.Open(rel)
	if err != nil {
		return info, "", baseUnreadable, nil
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, maxFileBytes+1))
	if err != nil {
		return info, "", baseUnreadable, nil
	}
	if len(data) > maxFileBytes {
		return nil, "", "", fmt.Errorf("the file is larger than %d KiB; it is not edited through the AI", maxFileBytes/1024)
	}
	return info, string(data), sha(data), nil
}

// currentBase gibt Inhalt und Hash der bestehenden Datei zurück (bei einer neuen Datei beides leer).
func currentBase(pol policy.Policy, real string, exists bool) (string, string, error) {
	if !exists {
		return "", "", nil
	}
	_, content, hash, err := readConfined(pol, real)
	return content, hash, err
}

func classifyFileWrite(args Args) (Action, error) {
	path := args.text("path")
	if path == "" {
		return Action{}, errors.New("path is required (absolute, e.g. /etc/nginx/conf.d/site.conf)")
	}
	mode := strings.ToLower(args.text("mode"))
	if mode == "" {
		mode = "replace"
	}
	if mode != "replace" && mode != "append" {
		return Action{}, errors.New("mode must be replace or append")
	}
	content, _ := args["content"].(string)
	if content == "" {
		return Action{}, errors.New("content is required (the new text of the file)")
	}
	if len(content) > maxWriteBytes || !utf8.ValidString(content) || strings.ContainsRune(content, 0) {
		return Action{}, fmt.Errorf("content must be valid text of at most %d KiB", maxWriteBytes/1024)
	}
	real, exists, err := tools.ResolveParent(path)
	if err != nil {
		return Action{}, err
	}
	// Der Hash der bestehenden Datei wird erst in Manager.Prepare eingetragen, nachdem die Richtlinie den Pfad erlaubt hat
	// (bindBase); der Root-Helfer bekommt ihn mit dem Plan zurück.
	base, _ := args["base_sha256"].(string)
	if mode == "replace" && strings.HasSuffix(strings.ToLower(real), ".json") {
		var tmp any
		if err := json.Unmarshal([]byte(content), &tmp); err != nil {
			return Action{}, fmt.Errorf("the new content is not valid JSON: %v", err)
		}
	}
	norm := Args{"path": real, "content": content, "mode": mode, "base_sha256": base}
	a := Action{Tool: ToolFileWrite, Class: 2, Root: true, Timeout: 30 * time.Second, Args: norm}
	a.Command = fmt.Sprintf("write file %s (%s, %d bytes, sha256 %s)", real, mode, len(content), sha([]byte(content))[:16])
	verb := "write"
	switch {
	case !exists:
		verb = "create"
	case mode == "append":
		verb = "append"
	}
	a.Summary = T("file.summary."+verb, strings.ToUpper(verb[:1])+verb[1:]+" file {path}", "path", real)
	switch {
	case writeDenied(real):
		a.Class = 3
		a.Reason = T("file.denied", "This path belongs to the system, to login, to booting or to the agent itself and is never written through the AI.")
	case !exists:
		a.Reason = T("file.reason_new", "Creates a new file.")
		a.Undo = Plain("rm " + real)
	default:
		a.Reason = T("file.reason", "Changes a file on the server. The previous version is kept next to it as a backup.")
		a.Undo = T("file.undo", "Restore the backup copy {path}.copilot-bak-<date> that is kept next to the file.", "path", real)
	}
	a.Check = []string{"stat", "-c", "%n: %s bytes, mode %a, owner %U:%G, modified %y", real}
	return a, nil
}

func (m *Manager) previewFileWrite(a Action) (Msg, Action, error) {
	real, mode, content := a.Args.text("path"), a.Args.text("mode"), ""
	content, _ = a.Args["content"].(string)
	_, exists, err := tools.ResolveParent(real)
	if err != nil {
		return Msg{}, a, err
	}
	old, hash, err := currentBase(m.Policy(), real, exists)
	if err != nil {
		return Msg{}, a, err
	}
	if hash == baseUnreadable {
		return T("file.preview_unreadable", "The current content of {path} cannot be read by the agent user, so no comparison is shown. The new text is written as given.", "path", real), a, nil
	}
	next := content
	if mode == "append" {
		next = old + content
	}
	if !exists {
		return filePreviewNew(real, next), a, nil
	}
	diff, added, removed := UnifiedDiff(old, next)
	if diff == "" {
		return T("file.preview_same", "The file already has exactly this content; nothing would change."), a, nil
	}
	head := T("file.preview_diff", "Changes to {path}: {added} line(s) added, {removed} removed.", "path", real, "added", strconv.Itoa(added), "removed", strconv.Itoa(removed))
	head.Then = []Msg{Plain(clip(diff, 5000))}
	return head, a, nil
}

func filePreviewNew(real, content string) Msg {
	lines := strings.Count(content, "\n") + 1
	head := T("file.preview_new", "New file {path} with {lines} line(s):", "path", real, "lines", strconv.Itoa(lines))
	head.Then = []Msg{Plain(clip(content, 5000))}
	return head
}

func clip(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return strings.ToValidUTF8(s[:n], "") + "\n[... cut]"
}

// ApplyFileWrite schreibt die Datei (läuft im Root-Helfer). Es prüft noch einmal Pfad, Richtlinie und dass die Datei seit der
// Vorschau unverändert ist, legt eine Sicherungskopie an und ersetzt die Datei atomar (Besitzer und Rechte bleiben).
func ApplyFileWrite(a Action, pol policy.Policy) (string, error) {
	path, mode, base := a.Args.text("path"), a.Args.text("mode"), a.Args.text("base_sha256")
	content, _ := a.Args["content"].(string)
	real, exists, err := tools.ResolveParent(path)
	if err != nil {
		return "", err
	}
	if real != path {
		return "", errors.New("the path changed since the preview")
	}
	if writeDenied(real) || !pol.WriteAllowed(real) {
		return "", errors.New("writing to this path is not allowed")
	}
	old, hash, err := currentBase(pol, real, exists)
	if err != nil {
		return "", err
	}
	if base != baseUnreadable && hash != base {
		return "", errors.New("the file changed since the preview; please prepare the change again")
	}
	next := content
	if mode == "append" {
		next = old + content
	}
	if len(next) > maxFileBytes {
		return "", fmt.Errorf("the result would be larger than %d KiB", maxFileBytes/1024)
	}
	perm, uid, gid := os.FileMode(0o644), 0, 0
	var backup string
	if exists {
		info, _, _, err := readConfined(pol, real)
		if err != nil {
			return "", err
		}
		perm = info.Mode().Perm()
		if st, ok := info.Sys().(*syscall.Stat_t); ok {
			uid, gid = int(st.Uid), int(st.Gid)
		}
		data := []byte(old) // der Inhalt, dessen Hash gerade mit der Vorschau verglichen wurde
		if hash == baseUnreadable {
			return "", errors.New("the current content cannot be read, so no backup copy can be made")
		}
		backup = real + backupInfix + time.Now().UTC().Format("20060102-150405")
		if err := writeNew(backup, data, perm, uid, gid); err != nil {
			return "", fmt.Errorf("backup failed: %v", err)
		}
	}
	rnd := make([]byte, 6)
	_, _ = rand.Read(rnd)
	tmp := filepath.Join(filepath.Dir(real), "."+filepath.Base(real)+".copilot-tmp-"+hex.EncodeToString(rnd))
	if err := writeNew(tmp, []byte(next), perm, uid, gid); err != nil {
		return "", err
	}
	if err := os.Rename(tmp, real); err != nil {
		_ = os.Remove(tmp)
		return "", err
	}
	if exists {
		pruneBackups(real)
	}
	out := fmt.Sprintf("Wrote %d bytes to %s (mode %04o).\n", len(next), real, perm)
	if backup != "" {
		out += "Backup of the previous version: " + backup + "\n"
	}
	return out, nil
}

func writeNew(path string, data []byte, perm os.FileMode, uid, gid int) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL|syscall.O_NOFOLLOW, 0o600)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		if !ok {
			_ = os.Remove(path)
		}
	}()
	if _, err := f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err := f.Chmod(perm); err != nil {
		f.Close()
		return err
	}
	if os.Geteuid() == 0 {
		if err := f.Chown(uid, gid); err != nil {
			f.Close()
			return err
		}
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	ok = true
	return nil
}

// pruneBackups behält die neuesten Sicherungskopien einer Datei.
func pruneBackups(real string) {
	dir, name := filepath.Dir(real), filepath.Base(real)+backupInfix
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	var names []string
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), name) && e.Type().IsRegular() {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)
	for len(names) > keepBackups {
		_ = os.Remove(filepath.Join(dir, names[0]))
		names = names[1:]
	}
}

// bindBase trägt bei einem Auftrag zum Schreiben den Hash der bestehenden Datei ein, falls noch keiner gesetzt ist. Das geschieht
// erst, nachdem die Richtlinie den Pfad erlaubt hat; gelesen wird nur innerhalb des erlaubten Ordners.
func bindBase(pol policy.Policy, a Action) (Action, error) {
	if a.Tool != ToolFileWrite || a.Args.text("base_sha256") != "" {
		return a, nil
	}
	real := a.Args.text("path")
	_, exists, err := tools.ResolveParent(real)
	if err != nil {
		return a, err
	}
	_, hash, err := currentBase(pol, real, exists)
	if err != nil {
		return a, err
	}
	a.Args = copyArgs(a.Args)
	a.Args["base_sha256"] = hash
	return a, nil
}

func copyArgs(in Args) Args {
	out := make(Args, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}
