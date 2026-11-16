package plan

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
)

func writePolicy(dir string) policy.Policy {
	p := policy.Default()
	p.Operate = true
	p.WritePaths = []string{dir}
	return p
}

func TestClassifyFileWrite(t *testing.T) {
	dir := t.TempDir()
	existing := filepath.Join(dir, "app.conf")
	if err := os.WriteFile(existing, []byte("a=1\n"), 0o640); err != nil {
		t.Fatal(err)
	}
	a, err := classifyFileWrite(Args{"path": existing, "content": "a=2\n"})
	if err != nil {
		t.Fatal(err)
	}
	if a.Class != 2 || !a.Root || a.Tool != ToolFileWrite || a.Undo.Code != "file.undo" {
		t.Fatalf("unexpected action: %+v", a)
	}
	a, err = classifyFileWrite(Args{"path": filepath.Join(dir, "new.conf"), "content": "x\n"})
	if err != nil || a.Reason.Code != "file.reason_new" {
		t.Fatalf("new file: %v %+v", err, a.Reason)
	}
	for _, p := range []string{"/etc/shadow", "/etc/ssh/sshd_config", "/etc/copilot-agent/policy", "/root/x.conf", "/usr/bin/tool"} {
		a, err := classifyFileWrite(Args{"path": p, "content": "x\n"})
		if err != nil {
			continue // a missing directory is refused as well
		}
		if a.Class != 3 {
			t.Errorf("%s must be class 3, got %d", p, a.Class)
		}
	}
	bad := []Args{
		{"path": "relative.conf", "content": "x"},
		{"path": existing, "content": ""},
		{"path": existing, "content": "x", "mode": "delete"},
		{"path": filepath.Join(dir, "../etc/passwd"), "content": "x"},
		{"path": filepath.Join(dir, "a b"), "content": "x"},
		{"path": filepath.Join(dir, "d.json"), "content": "{not json"},
		{"path": existing, "content": strings.Repeat("x", maxWriteBytes+1)},
		{"path": existing, "content": "a\x00b"},
	}
	for _, args := range bad {
		if _, err := classifyFileWrite(args); err == nil {
			t.Errorf("args %v should be refused", args)
		}
	}
}

// prep entspricht dem, was Manager.Prepare mit einem Auftrag zum Schreiben macht: einstufen, dann den Hash der Datei binden.
func prep(dir string, args Args) (Action, error) {
	a, err := classifyFileWrite(args)
	if err != nil {
		return a, err
	}
	return bindBase(writePolicy(dir), a)
}

func TestApplyFileWriteReplaceBackupAndMode(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "app.conf")
	if err := os.WriteFile(path, []byte("a=1\n"), 0o640); err != nil {
		t.Fatal(err)
	}
	a, err := prep(dir, Args{"path": path, "content": "a=2\n"})
	if err != nil {
		t.Fatal(err)
	}
	out, err := ApplyFileWrite(a, writePolicy(dir))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "Backup of the previous version") {
		t.Errorf("no backup note in %q", out)
	}
	if got, _ := os.ReadFile(path); string(got) != "a=2\n" {
		t.Errorf("file content %q", got)
	}
	info, _ := os.Stat(path)
	if info.Mode().Perm() != 0o640 {
		t.Errorf("mode changed to %v", info.Mode().Perm())
	}
	backups, _ := filepath.Glob(path + backupInfix + "*")
	if len(backups) != 1 {
		t.Fatalf("want 1 backup, got %v", backups)
	}
	if got, _ := os.ReadFile(backups[0]); string(got) != "a=1\n" {
		t.Errorf("backup content %q", got)
	}
	if left, _ := filepath.Glob(filepath.Join(dir, ".*copilot-tmp-*")); len(left) != 0 {
		t.Errorf("temporary files left: %v", left)
	}
}

func TestApplyFileWriteAppendAndCreate(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "log.txt")
	a, _ := prep(dir, Args{"path": path, "content": "one\n"})
	if _, err := ApplyFileWrite(a, writePolicy(dir)); err != nil {
		t.Fatal(err)
	}
	a, _ = prep(dir, Args{"path": path, "content": "two\n", "mode": "append"})
	if _, err := ApplyFileWrite(a, writePolicy(dir)); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(path); string(got) != "one\ntwo\n" {
		t.Errorf("content %q", got)
	}
}

func TestApplyFileWriteRefusals(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "app.conf")
	_ = os.WriteFile(path, []byte("a=1\n"), 0o644)
	a, _ := prep(dir, Args{"path": path, "content": "a=2\n"})

	// the file changed after the preview
	_ = os.WriteFile(path, []byte("a=changed\n"), 0o644)
	if _, err := ApplyFileWrite(a, writePolicy(dir)); err == nil || !strings.Contains(err.Error(), "changed since the preview") {
		t.Errorf("a changed file must be refused, got %v", err)
	}
	// directory not allowed by the policy
	other := t.TempDir()
	if _, err := ApplyFileWrite(a, writePolicy(other)); err == nil || !strings.Contains(err.Error(), "not allowed") {
		t.Errorf("policy must refuse, got %v", err)
	}
	// empty write_paths means nowhere
	p := writePolicy(dir)
	p.WritePaths = nil
	if _, err := ApplyFileWrite(a, p); err == nil {
		t.Error("empty write_paths must refuse")
	}
	// symlink as the last name is refused
	link := filepath.Join(dir, "link.conf")
	_ = os.Symlink(path, link)
	if _, err := prep(dir, Args{"path": link, "content": "x"}); err == nil {
		t.Error("symbolic link target must be refused")
	}
	// a path through a symlinked directory is resolved and then checked against the policy
	linkDir := filepath.Join(t.TempDir(), "d")
	_ = os.Symlink(other, linkDir)
	if a2, err := prep(dir, Args{"path": filepath.Join(linkDir, "x.conf"), "content": "x"}); err == nil {
		if _, err := ApplyFileWrite(a2, writePolicy(dir)); err == nil {
			t.Error("a symlinked directory must not escape the policy")
		}
	}
}

func TestApplyFileWriteKeepsFiveBackups(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "app.conf")
	_ = os.WriteFile(path, []byte("v0\n"), 0o644)
	for i := 0; i < 8; i++ {
		// distinct backup names need distinct seconds, so create them by hand
		bak := path + backupInfix + "2020010" + string(rune('1'+i)) + "-000000"
		_ = os.WriteFile(bak, []byte("old"), 0o644)
	}
	a, _ := prep(dir, Args{"path": path, "content": "v1\n"})
	if _, err := ApplyFileWrite(a, writePolicy(dir)); err != nil {
		t.Fatal(err)
	}
	backups, _ := filepath.Glob(path + backupInfix + "*")
	if len(backups) != keepBackups {
		t.Errorf("want %d backups, got %d", keepBackups, len(backups))
	}
}

func TestWriteDenied(t *testing.T) {
	for _, p := range []string{"/etc/passwd", "/etc/ssh/sshd_config", "/home/u/.ssh/config", "/home/u/authorized_keys", "/etc/copilot-agent/policy", "/etc/systemd/system/copilot-agent.service", "/proc/1/x", "/boot/grub/grub.cfg"} {
		if !writeDenied(p) {
			t.Errorf("%s must be denied", p)
		}
	}
	for _, p := range []string{"/etc/nginx/nginx.conf", "/opt/app/config.yml", "/etc/systemd/system/myapp.service"} {
		if writeDenied(p) {
			t.Errorf("%s must be allowed", p)
		}
	}
}

func TestReadsStayInsideTheAllowedDirectory(t *testing.T) {
	dir := t.TempDir()
	outside := t.TempDir()
	secret := filepath.Join(outside, "secret.conf")
	if err := os.WriteFile(secret, []byte("outside\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	pol := writePolicy(dir)
	// a path outside the allowed directories is never read, not even for the comparison hash
	a, err := classifyFileWrite(Args{"path": secret, "content": "x\n"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := bindBase(pol, a); err == nil || !strings.Contains(err.Error(), "not allowed") {
		t.Errorf("a path outside write_paths must not be read, got %v", err)
	}
	// a link inside the allowed directory that points out of it is not followed
	link := filepath.Join(dir, "escape.conf")
	if err := os.Symlink(secret, link); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := readConfined(pol, link); err == nil {
		t.Error("a symbolic link leaving the allowed directory must not be followed")
	}
	// an ordinary file inside is read, with its hash
	inside := filepath.Join(dir, "ok.conf")
	if err := os.WriteFile(inside, []byte("a=1\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, content, hash, err := readConfined(pol, inside)
	if err != nil || content != "a=1\n" || hash != sha([]byte("a=1\n")) {
		t.Errorf("readConfined = %q %q %v", content, hash, err)
	}
}
