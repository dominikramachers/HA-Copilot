package tools

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/dominikramachers/ha-copilot/agent/internal/metrics"
)

// RootRead führt ein lesendes Werkzeug über den Root-Helfer aus (Docker). Wird beim Start gesetzt; nil = kein Helfer.
var RootRead func(ctx context.Context, tool string, args Args) (string, error)

var packageRe = regexp.MustCompile(`^[a-z0-9][a-z0-9+.\-]{0,99}(:[a-z0-9]{2,10})?$`)

const (
	fileReadMax   = 64 * 1024
	fileTailBytes = 256 * 1024
	listMax       = 200
)

// fileRead liest eine Textdatei (Anfang oder Ende) oder listet ein Verzeichnis. Läuft ohne besondere Rechte und lehnt Pfade ab,
// die nach Schlüsseln, Kennwörtern oder Token aussehen.
func fileRead(args Args) (string, error) {
	path := args.text("path")
	if path == "" {
		return "", errors.New("path is required (absolute, e.g. /etc/nginx/nginx.conf)")
	}
	real, err := ResolveExisting(path)
	if err != nil {
		return "", err
	}
	if SensitivePath(path) || SensitivePath(real) {
		return "", errors.New("refused: the path looks confidential (keys, passwords, tokens or secrets)")
	}
	info, err := os.Stat(real)
	if err != nil {
		return "", errors.New(errText(err))
	}
	if info.IsDir() {
		return listDir(real)
	}
	if !info.Mode().IsRegular() {
		return "", errors.New("not a regular file")
	}
	lines, err := args.number("lines", 100, 1, 400)
	if err != nil {
		return "", err
	}
	fromEnd := strings.EqualFold(args.text("from"), "end")
	f, err := os.Open(real)
	if err != nil {
		return "", errors.New(errText(err))
	}
	defer f.Close()
	size := info.Size()
	var data []byte
	if fromEnd && size > fileTailBytes {
		if _, err := f.Seek(size-fileTailBytes, io.SeekStart); err != nil {
			return "", err
		}
		data, err = io.ReadAll(io.LimitReader(f, fileTailBytes))
	} else {
		data, err = io.ReadAll(io.LimitReader(f, fileTailBytes))
	}
	if err != nil {
		return "", errors.New(errText(err))
	}
	if bytes.IndexByte(data[:min(len(data), 8192)], 0) >= 0 {
		return fmt.Sprintf("%s is a binary file (%d bytes), not shown.\n", real, size), nil
	}
	text := strings.ReplaceAll(string(data), "\r\n", "\n")
	all := strings.Split(strings.TrimRight(text, "\n"), "\n")
	truncated := ""
	switch {
	case fromEnd && len(all) > lines:
		all = all[len(all)-lines:]
		truncated = fmt.Sprintf(" (last %d lines)", lines)
	case !fromEnd && len(all) > lines:
		all = all[:lines]
		truncated = fmt.Sprintf(" (first %d lines)", lines)
	}
	body := strings.Join(all, "\n")
	if len(body) > fileReadMax {
		body = strings.ToValidUTF8(body[:fileReadMax], "") + "\n[... cut at 64 KiB]"
	}
	return fmt.Sprintf("== %s: %d bytes%s ==\n%s\n", real, size, truncated, body), nil
}

func listDir(dir string) (string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return "", errors.New(errText(err))
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
	var b strings.Builder
	fmt.Fprintf(&b, "== %s: directory, %d entries ==\n", dir, len(entries))
	for i, e := range entries {
		if i >= listMax {
			fmt.Fprintf(&b, "[... and %d more]\n", len(entries)-listMax)
			break
		}
		info, err := e.Info()
		if err != nil {
			fmt.Fprintf(&b, "%s\n", e.Name())
			continue
		}
		kind := "-"
		switch {
		case e.IsDir():
			kind = "d"
		case e.Type()&os.ModeSymlink != 0:
			kind = "l"
		}
		fmt.Fprintf(&b, "%s %04o %10d %s %s\n", kind, info.Mode().Perm(), info.Size(), info.ModTime().UTC().Format("2006-01-02 15:04"), e.Name())
	}
	return b.String(), nil
}

// packageInfo zeigt Zustand und Herkunft eines Pakets (apt/dpkg, nur lesend).
func packageInfo(ctx context.Context, args Args) (string, error) {
	name := args.text("package")
	if !packageRe.MatchString(name) {
		return "", errors.New("package is required (lower-case package name without a version)")
	}
	var b strings.Builder
	if out, err := Run(ctx, "dpkg-query", "-W", "-f=Package: ${Package}\nStatus: ${Status}\nInstalled version: ${Version}\nSection: ${Section}\nInstalled size (kB): ${Installed-Size}\nDepends: ${Depends}\n", name); err == nil {
		b.WriteString(out)
	} else {
		b.WriteString("Not installed.\n")
	}
	if out, err := Run(ctx, "apt-cache", "policy", name); err == nil && strings.TrimSpace(out) != "" {
		b.WriteString("\n-- apt policy --\n" + out)
	} else {
		b.WriteString("\nNo package of this name is known to apt (run apt update first?).\n")
	}
	if out, err := Run(ctx, "dpkg", "-L", name); err == nil {
		lines := strings.Split(strings.TrimRight(out, "\n"), "\n")
		shown := 0
		var picked []string
		for _, l := range lines {
			if strings.HasPrefix(l, "/etc/") && !strings.HasSuffix(l, "/") {
				picked = append(picked, l)
				if shown++; shown >= 15 {
					break
				}
			}
		}
		if len(picked) > 0 {
			b.WriteString("\n-- files below /etc from this package --\n" + strings.Join(picked, "\n") + "\n")
		}
	}
	return b.String(), nil
}

var containerRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`)

// DockerArgv prüft die Angaben und gibt den festen Befehl zurück. Es gibt nur lesende Unterbefehle, keine frei wählbaren Optionen,
// und „inspect“ zeigt bewusst keine Umgebungsvariablen (dort stehen oft Kennwörter).
func DockerArgv(args Args) ([]string, error) {
	switch what := args.text("what"); what {
	case "ps":
		return []string{"docker", "ps", "-a", "--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"}, nil
	case "stats":
		return []string{"docker", "stats", "--no-stream", "--format", "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"}, nil
	case "logs", "inspect":
		c := args.text("container")
		if !containerRe.MatchString(c) {
			return nil, errors.New("container is required (the name of the container)")
		}
		if what == "inspect" {
			return []string{"docker", "inspect", "--format", "{{.Name}} image={{.Config.Image}} state={{.State.Status}} restarts={{.RestartCount}} started={{.State.StartedAt}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}\nports={{json .NetworkSettings.Ports}}\nmounts:{{range .Mounts}}\n  {{.Type}} {{.Source}} -> {{.Destination}} ({{.Mode}}){{end}}", "--", c}, nil
		}
		lines, err := args.number("lines", 50, 1, 200)
		if err != nil {
			return nil, err
		}
		return []string{"docker", "logs", "--tail", fmt.Sprint(lines), "--timestamps", "--", c}, nil
	}
	return nil, errors.New("what must be ps, stats, logs or inspect")
}

func docker(ctx context.Context, args Args) (string, error) {
	if _, err := DockerArgv(args); err != nil {
		return "", err
	}
	if RootRead == nil {
		return "", errors.New("Docker can only be read through the root helper, which is not available on this server")
	}
	return RootRead(ctx, "docker", args)
}

func metricsHistory(args Args) (string, error) {
	minutes, err := args.number("minutes", 60, 5, 1440)
	if err != nil {
		return "", err
	}
	return metrics.Default.Report(minutes), nil
}

// MetricsFile ist der Name der gespeicherten Messwerte im Zustandsverzeichnis.
const MetricsFile = "metrics.json"

// SaveEvery speichert die Messwerte in diesem Abstand.
const SaveEvery = 5 * time.Minute

// MetricsPath ergibt den Pfad der Messwertdatei in einem Zustandsverzeichnis.
func MetricsPath(dir string) string { return filepath.Join(dir, MetricsFile) }
