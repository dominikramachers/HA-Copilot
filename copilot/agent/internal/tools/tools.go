// Package tools enthält die lesenden Werkzeuge, die der Hub dem Agenten auftragen darf. Es gibt keine Shell und keinen frei
// wählbaren Befehl: jedes Werkzeug ist eine feste Liste von Programmen mit geprüften Argumenten.
package tools

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"os"
	"regexp"
	"runtime"
	"strconv"
	"strings"
)

// Names sind die Werkzeuge in der Reihenfolge des Hubs (READ_TOOLS in app/servers.py).
var Names = []string{"system", "disks", "memory", "load", "processes", "services_failed", "service", "journal", "network", "updates", "users", "metrics", "file_read", "package_info", "docker", "update_candidates"}

var (
	unitRe     = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9:_.@\\-]{0,99}$`)
	priorities = map[string]bool{"emerg": true, "alert": true, "crit": true, "err": true, "warning": true, "notice": true, "info": true, "debug": true}
)

// Args sind die Argumente eines Aufrufs, wie sie der Hub schickt (unbekannte Felder werden ignoriert).
type Args map[string]any

func (a Args) text(key string) string {
	s, _ := a[key].(string)
	return strings.TrimSpace(s)
}

// number liest eine ganze Zahl (JSON liefert float64) mit Grenzen; fehlt sie, gilt der Vorgabewert.
func (a Args) number(key string, def, low, high int) (int, error) {
	v, ok := a[key]
	if !ok || v == nil {
		return def, nil
	}
	f, ok := v.(float64)
	if !ok || f != float64(int(f)) {
		return 0, fmt.Errorf("%s must be a whole number", key)
	}
	n := int(f)
	if n < low {
		n = low
	}
	if n > high {
		n = high
	}
	return n, nil
}

// Call führt ein Werkzeug aus. Die Antwort ist bereits bereinigt und gekürzt.
func Call(ctx context.Context, name string, args Args) (string, error) {
	var (
		out string
		err error
	)
	switch name {
	case "system":
		out, err = system(ctx)
	case "disks":
		out, err = Run(ctx, "df", "-hT", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay", "-x", "efivarfs")
		if err == nil {
			inodes, _ := Run(ctx, "df", "-i", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay", "-x", "efivarfs")
			out += "\nInodes:\n" + inodes
		}
	case "memory":
		out, err = memory(ctx)
	case "load":
		out, err = load()
	case "processes":
		out, err = processes(ctx)
	case "services_failed":
		out, err = Run(ctx, "systemctl", "--failed", "--no-pager", "--no-legend", "--plain")
		if err == nil && strings.TrimSpace(out) == "" {
			out = "No failed services.\n"
		}
	case "service":
		unit := args.text("unit")
		if !unitRe.MatchString(unit) {
			return "", errors.New("unit is missing or contains invalid characters")
		}
		out, err = Run(ctx, "systemctl", "status", "--no-pager", "--full", "-n", "15", "--", unit)
	case "journal":
		out, err = journal(ctx, args)
	case "network":
		out, err = network(ctx)
	case "updates":
		out, err = updates(ctx)
	case "users":
		out, err = users(ctx)
	case "metrics":
		out, err = metricsHistory(args)
	case "file_read":
		out, err = fileRead(args)
	case "package_info":
		out, err = packageInfo(ctx, args)
	case "docker":
		out, err = docker(ctx, args)
	case "update_candidates":
		// strukturierte Antwort (JSON) für den Hub: nicht durch Redact/Kürzen verändern, updateCandidates hält die Größe selbst ein
		raw, cerr := updateCandidates(ctx, args)
		if cerr != nil {
			return "", cerr
		}
		return raw, nil
	default:
		return "", errors.New("unknown tool")
	}
	if err != nil {
		return "", err
	}
	return Clean(Redact(out)), nil
}

func journal(ctx context.Context, args Args) (string, error) {
	lines, err := args.number("lines", 50, 1, 200)
	if err != nil {
		return "", err
	}
	argv := []string{"--no-pager", "-o", "short-iso", "-n", strconv.Itoa(lines)}
	if unit := args.text("unit"); unit != "" {
		if !unitRe.MatchString(unit) {
			return "", errors.New("unit contains invalid characters")
		}
		argv = append(argv, "-u", unit)
	}
	if p := args.text("priority"); p != "" {
		if !priorities[p] {
			return "", errors.New("priority must be emerg, alert, crit, err, warning, notice, info or debug")
		}
		argv = append(argv, "-p", p)
	}
	if _, ok := args["since_minutes"]; ok {
		minutes, err := args.number("since_minutes", 0, 1, 10080)
		if err != nil {
			return "", err
		}
		argv = append(argv, fmt.Sprintf("--since=-%dmin", minutes))
	}
	return Run(ctx, "journalctl", argv...)
}

func readFile(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return string(data)
}

// OSRelease liefert PRETTY_NAME aus dem Inhalt von os-release.
func OSRelease(content string) string {
	sc := bufio.NewScanner(strings.NewReader(content))
	for sc.Scan() {
		line := sc.Text()
		if strings.HasPrefix(line, "PRETTY_NAME=") {
			return strings.Trim(strings.TrimPrefix(line, "PRETTY_NAME="), `"'`)
		}
	}
	return ""
}

func system(ctx context.Context) (string, error) {
	var b strings.Builder
	host, _ := os.Hostname()
	fmt.Fprintf(&b, "Hostname: %s\n", host)
	if name := OSRelease(readFile("/etc/os-release")); name != "" {
		fmt.Fprintf(&b, "System: %s\n", name)
	}
	fmt.Fprintf(&b, "Kernel: %s\n", strings.TrimSpace(readFile("/proc/sys/kernel/osrelease")))
	fmt.Fprintf(&b, "Architecture: %s, CPUs: %d\n", runtime.GOARCH, runtime.NumCPU())
	if up := Uptime(); up > 0 {
		fmt.Fprintf(&b, "Uptime: %s\n", HumanDuration(up))
	}
	if virt, err := Run(ctx, "systemd-detect-virt"); err == nil {
		fmt.Fprintf(&b, "Virtualization: %s\n", strings.TrimSpace(strings.Split(virt, "\n[")[0]))
	}
	if _, err := os.Stat("/run/reboot-required"); err == nil {
		b.WriteString("Reboot required: yes\n")
	}
	return b.String(), nil
}

// Uptime in Sekunden (0 = unbekannt).
func Uptime() int {
	fields := strings.Fields(readFile("/proc/uptime"))
	if len(fields) == 0 {
		return 0
	}
	f, err := strconv.ParseFloat(fields[0], 64)
	if err != nil {
		return 0
	}
	return int(f)
}

// HumanDuration formatiert Sekunden als „3 Tage 4 Std 5 Min“.
func HumanDuration(seconds int) string {
	days, rest := seconds/86400, seconds%86400
	hours, minutes := rest/3600, (rest%3600)/60
	switch {
	case days > 0:
		return fmt.Sprintf("%dd %dh %dm", days, hours, minutes)
	case hours > 0:
		return fmt.Sprintf("%dh %dm", hours, minutes)
	default:
		return fmt.Sprintf("%dm", minutes)
	}
}

// MemInfo liest die Werte aus /proc/meminfo-Text (in kB).
func MemInfo(content string) map[string]int {
	out := map[string]int{}
	for _, line := range strings.Split(content, "\n") {
		key, rest, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		fields := strings.Fields(rest)
		if len(fields) == 0 {
			continue
		}
		if n, err := strconv.Atoi(fields[0]); err == nil {
			out[key] = n
		}
	}
	return out
}

// MemUsage gibt Gesamtgröße in MB und belegten Anteil in Prozent (verfügbarer Speicher zählt als frei).
func MemUsage(content string) (totalMB int, usedPct float64, ok bool) {
	m := MemInfo(content)
	total, avail := m["MemTotal"], m["MemAvailable"]
	if total <= 0 || avail < 0 || avail > total {
		return 0, 0, false
	}
	return total / 1024, float64(total-avail) * 100 / float64(total), true
}

func memory(ctx context.Context) (string, error) {
	out, err := Run(ctx, "free", "-m")
	if err != nil {
		return "", err
	}
	m := MemInfo(readFile("/proc/meminfo"))
	if total := m["MemTotal"]; total > 0 {
		out += fmt.Sprintf("\nAvailable: %d MB of %d MB (%.0f %% used)\n", m["MemAvailable"]/1024, total/1024, float64(total-m["MemAvailable"])*100/float64(total))
	}
	return out, nil
}

func load() (string, error) {
	fields := strings.Fields(readFile("/proc/loadavg"))
	if len(fields) < 3 {
		return "", errors.New("load not readable")
	}
	return fmt.Sprintf("Load (1/5/15 min): %s %s %s\nCPUs: %d\n", fields[0], fields[1], fields[2], runtime.NumCPU()), nil
}

// head behält die ersten n Zeilen.
func head(s string, n int) string {
	lines := strings.Split(strings.TrimRight(s, "\n"), "\n")
	if len(lines) > n {
		lines = lines[:n]
	}
	return strings.Join(lines, "\n") + "\n"
}

func processes(ctx context.Context) (string, error) {
	cpu, err := Run(ctx, "ps", "-eo", "pid,user:12,pcpu,pmem,etime,comm", "--sort=-pcpu")
	if err != nil {
		return "", err
	}
	mem, err := Run(ctx, "ps", "-eo", "pid,user:12,pcpu,pmem,etime,comm", "--sort=-pmem")
	if err != nil {
		return "", err
	}
	return "By CPU:\n" + head(cpu, 13) + "\nBy memory:\n" + head(mem, 13), nil
}

func network(ctx context.Context) (string, error) {
	var b strings.Builder
	addr, err := Run(ctx, "ip", "-brief", "address")
	if err != nil {
		return "", err
	}
	b.WriteString("Addresses:\n" + addr)
	if route, err := Run(ctx, "ip", "route"); err == nil {
		b.WriteString("\nRoutes:\n" + head(route, 20))
	}
	if ports, err := Run(ctx, "ss", "-tuln"); err == nil {
		b.WriteString("\nListening ports:\n" + head(ports, 60))
	}
	return b.String(), nil
}

func updates(ctx context.Context) (string, error) {
	if PackageManager() == PkgDnf {
		return dnfUpdatesText(ctx)
	}
	out, err := Run(ctx, "apt", "list", "--upgradable")
	if err != nil {
		return "", err
	}
	var packages []string
	for _, line := range strings.Split(out, "\n") {
		if strings.Contains(line, "[upgradable") {
			packages = append(packages, line)
		}
	}
	var b strings.Builder
	fmt.Fprintf(&b, "Available updates: %d\n", len(packages))
	for i, line := range packages {
		if i >= 60 {
			fmt.Fprintf(&b, "... and %d more\n", len(packages)-60)
			break
		}
		b.WriteString(line + "\n")
	}
	if _, err := os.Stat("/run/reboot-required"); err == nil {
		b.WriteString("Reboot required: yes\n")
	}
	return b.String(), nil
}

func users(ctx context.Context) (string, error) {
	var b strings.Builder
	if out, err := Run(ctx, "who", "-u"); err == nil {
		b.WriteString("Logged in:\n")
		if strings.TrimSpace(out) == "" {
			out = "(nobody)\n"
		}
		b.WriteString(out)
	}
	if out, err := Run(ctx, "last", "-n", "10", "-w"); err == nil {
		b.WriteString("\nRecent logins:\n" + out)
	}
	if b.Len() == 0 {
		return "", errors.New("who and last are not installed")
	}
	return b.String(), nil
}
