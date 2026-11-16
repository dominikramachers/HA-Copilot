// Package collect sammelt die Angaben der regelmäßigen Meldung (Heartbeat) an den Hub. Alles wird lokal und ohne Shell gelesen;
// der Hub prüft die Felder noch einmal streng (clean_heartbeat in app/servers.py).
package collect

import (
	"context"
	"net"
	"os"
	"runtime"
	"strconv"
	"strings"
	"syscall"

	"github.com/dominikramachers/ha-copilot/agent/internal/tools"
)

// Heartbeat ist die Meldung an den Hub. Die Feldnamen sind das Protokoll.
type Heartbeat struct {
	T               string   `json:"t"`
	Hostname        string   `json:"hostname"`
	FQDN            string   `json:"fqdn,omitempty"`
	IPs             []string `json:"ips"`
	OS              string   `json:"os,omitempty"`
	Kernel          string   `json:"kernel,omitempty"`
	Arch            string   `json:"arch"`
	AgentVersion    string   `json:"agent_version"`
	UptimeS         int      `json:"uptime_s"`
	Load1           float64  `json:"load1"`
	Load5           float64  `json:"load5"`
	Load15          float64  `json:"load15"`
	CPUs            int      `json:"cpus"`
	MemTotalMB      int      `json:"mem_total_mb"`
	MemUsedPct      float64  `json:"mem_used_pct"`
	DiskWorstPct    int      `json:"disk_worst_pct"`
	DiskWorstMount  string   `json:"disk_worst_mount,omitempty"`
	FailedUnits     int      `json:"failed_units"`
	FailedUnitNames []string `json:"failed_unit_names"`
	Updates         *int     `json:"updates,omitempty"` // nil = unbekannt (apt fehlt oder noch nicht geprüft)
	RebootRequired  bool     `json:"reboot_required"`
	// Etappe 2: was die lokale Richtlinie erlaubt (der Hub kann das nicht erweitern)
	Operate  bool `json:"operate"`
	MaxClass int  `json:"max_class"`
	Helper   bool `json:"helper"`
}

// Collector merkt sich Werte, die teuer zu bestimmen sind (apt) und deshalb nicht bei jeder Meldung neu gelesen werden.
type Collector struct {
	Version string
	// Annotate ergänzt die Meldung um Angaben, die nicht aus dem System gelesen werden (Richtlinie, Helfer).
	Annotate func(*Heartbeat)
	updates  *int
	ticks    int
}

// updatesEvery: apt wird nur bei jeder N-ten Meldung gefragt (bei 30 s Takt etwa alle 15 Minuten).
const updatesEvery = 30

func readFile(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return string(data)
}

// IPs liefert die nicht lokalen Adressen aller aktiven Schnittstellen (ohne Loopback und Link-Local).
func IPs() []string {
	var out []string
	ifaces, err := net.Interfaces()
	if err != nil {
		return out
	}
	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, a := range addrs {
			ipnet, ok := a.(*net.IPNet)
			if !ok || ipnet.IP.IsLoopback() || ipnet.IP.IsLinkLocalUnicast() {
				continue
			}
			out = append(out, ipnet.IP.String())
		}
	}
	if len(out) > 16 {
		out = out[:16]
	}
	return out
}

// ParseLoad liest die ersten drei Werte aus /proc/loadavg.
func ParseLoad(content string) (l1, l5, l15 float64) {
	f := strings.Fields(content)
	if len(f) < 3 {
		return
	}
	l1, _ = strconv.ParseFloat(f[0], 64)
	l5, _ = strconv.ParseFloat(f[1], 64)
	l15, _ = strconv.ParseFloat(f[2], 64)
	return
}

// skipFS sind Dateisysteme, die für „Platte voll“ keine Rolle spielen.
var skipFS = map[string]bool{
	"tmpfs": true, "devtmpfs": true, "squashfs": true, "overlay": true, "proc": true, "sysfs": true, "cgroup": true, "cgroup2": true,
	"devpts": true, "efivarfs": true, "securityfs": true, "debugfs": true, "tracefs": true, "mqueue": true, "hugetlbfs": true,
	"fusectl": true, "configfs": true, "pstore": true, "bpf": true, "autofs": true, "binfmt_misc": true, "ramfs": true, "nsfs": true,
	"fuse.lxcfs": true, "rpc_pipefs": true, "fuse.portal": true,
}

// Mount ist ein eingehängtes Dateisystem aus /proc/self/mounts.
type Mount struct{ Path, FS string }

// ParseMounts liest /proc/self/mounts und lässt Pseudo-Dateisysteme aus (jeder Pfad nur einmal).
func ParseMounts(content string) []Mount {
	seen := map[string]bool{}
	var out []Mount
	for _, line := range strings.Split(content, "\n") {
		f := strings.Fields(line)
		if len(f) < 3 || skipFS[f[2]] || !strings.HasPrefix(f[1], "/") {
			continue
		}
		path := strings.ReplaceAll(f[1], `\040`, " ")
		if seen[path] || strings.HasPrefix(path, "/snap/") || strings.HasPrefix(path, "/var/lib/docker/") {
			continue
		}
		seen[path] = true
		out = append(out, Mount{Path: path, FS: f[2]})
	}
	return out
}

// worstDisk gibt den am stärksten belegten Einhängepunkt (Prozent, ganze Zahl).
func worstDisk() (int, string) {
	worst, where := 0, ""
	for _, m := range ParseMounts(readFile("/proc/self/mounts")) {
		var st syscall.Statfs_t
		if err := syscall.Statfs(m.Path, &st); err != nil || st.Blocks == 0 {
			continue
		}
		used := st.Blocks - st.Bfree
		avail := st.Bavail
		// wie „df“: belegt / (belegt + für Nutzer frei)
		if used+avail == 0 {
			continue
		}
		pct := int((used*100 + (used + avail) - 1) / (used + avail))
		if pct > worst {
			worst, where = pct, m.Path
		}
	}
	return worst, where
}

// ParseFailedUnits liest die Ausgabe von „systemctl --failed --no-legend --plain“ (Name steht in der ersten Spalte).
func ParseFailedUnits(output string) []string {
	var names []string
	for _, line := range strings.Split(output, "\n") {
		f := strings.Fields(strings.TrimLeft(line, "●* "))
		if len(f) > 0 && strings.Contains(f[0], ".") && !strings.HasPrefix(f[0], "[") {
			names = append(names, f[0])
		}
	}
	return names
}

// ParseUpdates zählt die Zeilen von „apt list --upgradable“.
func ParseUpdates(output string) int {
	n := 0
	for _, line := range strings.Split(output, "\n") {
		if strings.Contains(line, "[upgradable") {
			n++
		}
	}
	return n
}

// Collect erstellt eine Meldung.
func (c *Collector) Collect(ctx context.Context) Heartbeat {
	host, _ := os.Hostname()
	hb := Heartbeat{
		T: "heartbeat", Hostname: host, IPs: IPs(), Arch: runtime.GOARCH, AgentVersion: c.Version,
		OS:      tools.OSRelease(readFile("/etc/os-release")),
		Kernel:  strings.TrimSpace(readFile("/proc/sys/kernel/osrelease")),
		UptimeS: tools.Uptime(), CPUs: runtime.NumCPU(), FailedUnitNames: []string{},
	}
	if fqdn, err := net.LookupCNAME(host); err == nil {
		hb.FQDN = strings.TrimSuffix(fqdn, ".")
		if hb.FQDN == host {
			hb.FQDN = ""
		}
	}
	hb.Load1, hb.Load5, hb.Load15 = ParseLoad(readFile("/proc/loadavg"))
	if total, pct, ok := tools.MemUsage(readFile("/proc/meminfo")); ok {
		hb.MemTotalMB, hb.MemUsedPct = total, pct
	}
	hb.DiskWorstPct, hb.DiskWorstMount = worstDisk()
	if out, err := tools.Run(ctx, "systemctl", "--failed", "--no-pager", "--no-legend", "--plain"); err == nil {
		if names := ParseFailedUnits(out); names != nil {
			hb.FailedUnitNames = names
		}
		hb.FailedUnits = len(hb.FailedUnitNames)
	}
	if _, err := os.Stat("/run/reboot-required"); err == nil {
		hb.RebootRequired = true
	}
	if c.ticks%updatesEvery == 0 {
		if out, err := tools.Run(ctx, "apt", "list", "--upgradable"); err == nil {
			n := ParseUpdates(out)
			c.updates = &n
		}
	}
	c.ticks++
	hb.Updates = c.updates
	if c.Annotate != nil {
		c.Annotate(&hb)
	}
	return hb
}
