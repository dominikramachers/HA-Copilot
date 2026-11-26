package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Das Werkzeug „update_candidates“ liefert dem Hub die Tatsachen zu allen ausstehenden Aktualisierungen (Name, alte und neue Fassung,
// Herkunft, Sicherheitsupdate ja/nein, angehalten, was ein Trockenlauf entfernen oder zusätzlich installieren würde). Es verändert
// nichts. Welche davon automatisch eingespielt werden, entscheidet der Hub nach seinen Regeln und den Schaltern der Person; der Agent
// führt später nur über die geprüfte Paketaktion aus (Einstufung, Prüfsumme, lokale Richtlinie).

const (
	maxCandidates  = 200
	maxReportBytes = 45000
	simBudget      = 70 * time.Second
	simWorkers     = 4
	simLimit       = 100
	aptListsDir    = "/var/lib/apt/lists"
	aptPolicyBatch = 40
)

// UpdateInfo ist eine ausstehende Aktualisierung.
type UpdateInfo struct {
	Name      string   `json:"name"`
	Arch      string   `json:"arch,omitempty"`
	Installed string   `json:"installed,omitempty"`
	Candidate string   `json:"candidate"`
	Archive   string   `json:"archive,omitempty"` // apt: Suite, z. B. bookworm-security; dnf: Quelle
	Origin    string   `json:"origin,omitempty"`  // apt: „Origin“ der Paketquelle (Debian, Ubuntu …); dnf: leer
	Official  bool     `json:"official"`          // aus den eigenen Quellen der Distribution
	Security  bool     `json:"security"`
	Held      bool     `json:"held,omitempty"`
	Removes   []string `json:"removes,omitempty"`  // würde der Trockenlauf entfernen
	Installs  []string `json:"installs,omitempty"` // zusätzliche (neue) Pakete laut Trockenlauf
	Checked   bool     `json:"checked"`            // Trockenlauf für dieses Paket gelaufen
}

// UpdateReport ist die Antwort des Werkzeugs.
type UpdateReport struct {
	Manager        string       `json:"manager"`
	Updates        []UpdateInfo `json:"updates"`
	More           int          `json:"more,omitempty"` // so viele weitere gab es, die nicht aufgeführt sind
	RebootRequired bool         `json:"reboot_required"`
	FreeMB         int64        `json:"free_mb"`
	Note           string       `json:"note,omitempty"`
}

// officialOrigins sind die Quellen, die zur Distribution gehören; alles andere gilt als Drittquelle.
func officialOrigin(origin string) bool {
	for _, p := range []string{"Debian", "Ubuntu", "Raspbian"} {
		if origin == p || strings.HasPrefix(origin, p) {
			return true
		}
	}
	return false
}

// officialDnfRepo erkennt die Standard-Quellen von Red Hat, Rocky, Alma, CentOS Stream und Fedora an ihrer Kennung.
var officialDnfRepo = regexp.MustCompile(`^(baseos|appstream|crb|extras|updates|fedora|powertools|highavailability|resilientstorage|rt|nfv|plus|cr|devel|rhel-[0-9a-z.-]*|ubi-[0-9a-z.-]*|rocky-[a-z]+|almalinux-[a-z]+|alma-[a-z]+)$`)

func isSecuritySuite(suite string) bool {
	s := strings.ToLower(suite)
	return strings.Contains(s, "-security") || strings.HasSuffix(s, "/updates")
}

// ParseAptUpgradable liest „apt list --upgradable“: „name/suite[,suite] neue-Fassung arch [upgradable from: alte-Fassung]“.
func ParseAptUpgradable(out string) []UpdateInfo {
	var res []UpdateInfo
	for _, line := range strings.Split(out, "\n") {
		if !strings.Contains(line, "[upgradable from:") {
			continue
		}
		f := strings.Fields(line)
		if len(f) < 3 || !strings.Contains(f[0], "/") {
			continue
		}
		name, suites, _ := strings.Cut(f[0], "/")
		u := UpdateInfo{Name: name, Candidate: f[1], Archive: suites}
		if len(f) >= 3 && !strings.HasPrefix(f[2], "[") {
			u.Arch = f[2]
		}
		if i := strings.Index(line, "[upgradable from:"); i >= 0 {
			u.Installed = strings.TrimSpace(strings.TrimSuffix(strings.TrimSpace(line[i+len("[upgradable from:"):]), "]"))
		}
		for _, s := range strings.Split(suites, ",") {
			if isSecuritySuite(s) {
				u.Security = true
			}
		}
		if !validPackageToken(u.Name) {
			continue
		}
		res = append(res, u)
	}
	return res
}

func validPackageToken(name string) bool {
	return debPackageRe.MatchString(name) || rpmPackageRe.MatchString(name)
}

type policyInfo struct {
	URL   string
	Suite string
}

// ParseAptPolicy liest „apt-cache policy“ und gibt je Paket die Quelle (Adresse und Suite) der Kandidaten-Fassung zurück.
func ParseAptPolicy(out string) map[string]policyInfo {
	res := map[string]policyInfo{}
	var name, candidate string
	inCandidate := false
	for _, raw := range strings.Split(out, "\n") {
		line := strings.TrimRight(raw, " \t\r")
		if line == "" {
			continue
		}
		if !strings.HasPrefix(line, " ") && strings.HasSuffix(line, ":") {
			name, candidate, inCandidate = strings.TrimSuffix(line, ":"), "", false
			continue
		}
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "Candidate:") {
			candidate = strings.TrimSpace(strings.TrimPrefix(trimmed, "Candidate:"))
			continue
		}
		f := strings.Fields(strings.TrimPrefix(trimmed, "***"))
		// Zeile der Fassung: „<Fassung> <Priorität>“
		if len(f) == 2 && isNumber(f[1]) && !isNumber(f[0]) {
			inCandidate = candidate != "" && f[0] == candidate
			continue
		}
		// Zeile der Quelle: „<Priorität> <Adresse> <Suite>/<Komponente> …“
		if inCandidate && len(f) >= 3 && isNumber(f[0]) {
			if _, seen := res[name]; seen {
				continue
			}
			suite, _, _ := strings.Cut(f[2], "/")
			if strings.HasPrefix(f[1], "/") || strings.HasPrefix(f[1], "file:") {
				continue // installierte Fassung (dpkg/status) oder lokale Quelle
			}
			res[name] = policyInfo{URL: f[1], Suite: suite}
		}
	}
	return res
}

func isNumber(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

// listFileBase macht aus der Adresse einer Quelle den Anfang des Dateinamens in /var/lib/apt/lists (so benennt apt sie).
func listFileBase(url string) string {
	url = strings.TrimRight(url, "/")
	if i := strings.Index(url, "://"); i >= 0 {
		url = url[i+3:]
	}
	if i := strings.LastIndex(url, "@"); i >= 0 {
		url = url[i+1:]
	}
	return strings.NewReplacer("/", "_", ":", "%3a").Replace(url)
}

// aptOrigin liest das Feld „Origin“ aus der Release-Datei der Quelle. Unbekannt (Datei fehlt, nicht lesbar) ergibt „“.
func aptOrigin(dir, url, suite string) string {
	if url == "" || suite == "" || strings.ContainsAny(suite, "/\\") || strings.Contains(suite, "..") {
		return ""
	}
	base := dir + "/" + listFileBase(url) + "_dists_" + suite
	for _, tail := range []string{"_InRelease", "_Release"} {
		data, err := os.ReadFile(base + tail)
		if err != nil {
			continue
		}
		for i, line := range strings.Split(string(data), "\n") {
			if i > 40 {
				break
			}
			if v, ok := strings.CutPrefix(line, "Origin:"); ok {
				return clipOrigin(strings.TrimSpace(v))
			}
		}
	}
	return ""
}

func clipOrigin(s string) string {
	s = Clean(s)
	s = strings.TrimSpace(s)
	if len(s) > 40 {
		s = s[:40]
	}
	return s
}

// ParseAptSim liest den Trockenlauf von apt-get (-s): „Remv name [fassung]“ entfernt, „Inst name …“ installiert.
func ParseAptSim(out string) (removes, installs []string) {
	for _, line := range strings.Split(out, "\n") {
		f := strings.Fields(line)
		if len(f) < 2 {
			continue
		}
		switch f[0] {
		case "Remv":
			removes = append(removes, f[1])
		case "Inst":
			installs = append(installs, f[1])
		}
	}
	return removes, installs
}

// ParseDnfUpdateEntries liest „dnf check-update“ in Einträge (Name, Architektur, neue Fassung, Quelle).
func ParseDnfUpdateEntries(output string) []UpdateInfo {
	var res []UpdateInfo
	for _, line := range ParseDnfUpdates(output) {
		f := strings.Fields(line)
		if len(f) != 3 {
			continue
		}
		i := strings.LastIndex(f[0], ".")
		name, arch := f[0], ""
		if i > 0 {
			name, arch = f[0][:i], f[0][i+1:]
		}
		if !rpmPackageRe.MatchString(name) {
			continue
		}
		res = append(res, UpdateInfo{Name: name, Arch: arch, Candidate: f[1], Archive: f[2], Official: officialDnfRepo.MatchString(f[2])})
	}
	return res
}

func freeMB(path string) int64 {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return -1
	}
	return int64(st.Bavail) * int64(st.Bsize) / (1024 * 1024)
}

// updateCandidates sammelt die Tatsachen (nur lesend).
func updateCandidates(ctx context.Context, args Args) (string, error) {
	report := UpdateReport{Manager: PackageManager(), FreeMB: freeMB("/var")}
	var err error
	switch report.Manager {
	case PkgApt:
		err = aptCandidates(ctx, &report, args["simulate"] != false)
	case PkgDnf:
		err = dnfCandidates(ctx, &report)
	default:
		return "", fmt.Errorf("this server has no supported package manager (apt or dnf)")
	}
	if err != nil {
		return "", err
	}
	if report.Updates == nil {
		report.Updates = []UpdateInfo{}
	}
	raw, _ := json.Marshal(report)
	// Antwortgröße einhalten (sonst würde die Übertragung abgeschnitten und das JSON ungültig)
	for len(raw) > maxReportBytes && len(report.Updates) > 1 {
		cut := len(report.Updates) / 10
		if cut < 1 {
			cut = 1
		}
		report.More += cut
		report.Updates = report.Updates[:len(report.Updates)-cut]
		raw, _ = json.Marshal(report)
	}
	return string(raw), nil
}

func aptCandidates(ctx context.Context, r *UpdateReport, simulate bool) error {
	out, err := Run(ctx, "apt", "list", "--upgradable")
	if err != nil {
		return err
	}
	list := ParseAptUpgradable(out)
	sort.Slice(list, func(i, j int) bool { return list[i].Name < list[j].Name })
	if len(list) > maxCandidates {
		r.More = len(list) - maxCandidates
		list = list[:maxCandidates]
	}
	if _, statErr := os.Stat("/run/reboot-required"); statErr == nil {
		r.RebootRequired = true
	}
	if len(list) == 0 {
		return nil
	}
	held := map[string]bool{}
	if h, err := Run(ctx, "apt-mark", "showhold"); err == nil {
		for _, n := range strings.Fields(h) {
			held[n] = true
		}
	}
	// Herkunft der Kandidaten-Fassung
	sources := map[string]policyInfo{}
	for i := 0; i < len(list); i += aptPolicyBatch {
		end := i + aptPolicyBatch
		if end > len(list) {
			end = len(list)
		}
		args := []string{"policy"}
		for _, u := range list[i:end] {
			args = append(args, u.Name)
		}
		if pol, err := Run(ctx, "apt-cache", args...); err == nil {
			for k, v := range ParseAptPolicy(pol) {
				sources[k] = v
			}
		}
	}
	origins := map[string]string{}
	for i := range list {
		u := &list[i]
		u.Held = held[u.Name]
		if src, ok := sources[u.Name]; ok {
			key := src.URL + " " + src.Suite
			if _, seen := origins[key]; !seen {
				origins[key] = aptOrigin(aptListsDir, src.URL, src.Suite)
			}
			u.Origin = origins[key]
			if u.Archive == "" {
				u.Archive = src.Suite
			}
		}
		u.Official = officialOrigin(u.Origin)
	}
	if simulate {
		simulateAll(ctx, list)
	}
	r.Updates = list
	return nil
}

// simulateAll lässt je Paket einen Trockenlauf laufen (apt-get -s install --only-upgrade). So ist bekannt, welches Paket etwas
// entfernen würde. Die Zeit ist begrenzt; was nicht mehr drankommt, bleibt „Checked: false“.
func simulateAll(ctx context.Context, list []UpdateInfo) {
	ctx, cancel := context.WithTimeout(ctx, simBudget)
	defer cancel()
	var wg sync.WaitGroup
	sem := make(chan struct{}, simWorkers)
	for i := range list {
		if i >= simLimit {
			break
		}
		wg.Add(1)
		go func(u *UpdateInfo) {
			defer wg.Done()
			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				return
			}
			out, code, err := RunWith(ctx, Opts{Timeout: 40 * time.Second, Env: []string{"DEBIAN_FRONTEND=noninteractive"}},
				"apt-get", "-s", "-o", "Debug::NoLocking=1", "install", "--only-upgrade", "--", u.Name)
			if err != nil || code != 0 {
				return
			}
			rem, inst := ParseAptSim(out)
			for _, n := range rem {
				if validPackageToken(n) {
					u.Removes = append(u.Removes, n)
				}
			}
			for _, n := range inst {
				if n != u.Name && validPackageToken(n) {
					u.Installs = append(u.Installs, n)
				}
			}
			u.Checked = true
		}(&list[i])
	}
	wg.Wait()
}

func dnfCandidates(ctx context.Context, r *UpdateReport) error {
	all, err := dnfCheck(ctx, false)
	if err != nil {
		return err
	}
	list := ParseDnfUpdateEntries(all)
	if len(list) > 0 {
		if sec, err := dnfCheck(ctx, true); err == nil {
			secNames := map[string]bool{}
			for _, u := range ParseDnfUpdateEntries(sec) {
				secNames[u.Name+"."+u.Arch] = true
			}
			for i := range list {
				list[i].Security = secNames[list[i].Name+"."+list[i].Arch]
			}
		} else {
			r.Note = "Security updates could not be told apart (dnf was not able to list them)."
		}
	}
	sort.Slice(list, func(i, j int) bool { return list[i].Name < list[j].Name })
	if len(list) > maxCandidates {
		r.More = len(list) - maxCandidates
		list = list[:maxCandidates]
	}
	if len(list) > 0 {
		installed := map[string]string{}
		args := []string{"-q", "--qf", "%{NAME} %{VERSION}-%{RELEASE}\\n"}
		for _, u := range list {
			args = append(args, u.Name)
		}
		if out, code, err := RunWith(ctx, Opts{}, "rpm", args...); err == nil && code == 0 {
			for _, line := range strings.Split(out, "\n") {
				if f := strings.Fields(line); len(f) == 2 {
					if _, seen := installed[f[0]]; !seen {
						installed[f[0]] = f[1]
					}
				}
			}
		}
		for i := range list {
			list[i].Installed = installed[list[i].Name]
		}
	}
	r.RebootRequired = DnfRebootRequired(ctx)
	r.Updates = list
	return nil
}

func dnfCheck(ctx context.Context, security bool) (string, error) {
	if RootRead == nil {
		return "", fmt.Errorf("the root helper is not available, so dnf cannot be asked for updates")
	}
	args := Args{}
	if security {
		args["security"] = true
	}
	return RootRead(ctx, "pkg_check", args)
}
