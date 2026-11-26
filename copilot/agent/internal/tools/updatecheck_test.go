package tools

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const aptUpgradable = `Listing...
openssl/stable-security 3.0.15-1~deb12u1 amd64 [upgradable from: 3.0.14-1~deb12u1]
nginx/stable,stable-updates 1.22.1-9+deb12u1 amd64 [upgradable from: 1.22.1-9]
linux-image-amd64/stable-security 6.1.115-1 amd64 [upgradable from: 6.1.112-1]
foo/ppa.example 2.0 all [upgradable from: 1.0]
Bad Line/stable 1 amd64 [upgradable from: 1]
`

func TestParseAptUpgradable(t *testing.T) {
	got := ParseAptUpgradable(aptUpgradable)
	if len(got) != 4 {
		t.Fatalf("erwartet 4 Einträge, erhalten %d: %+v", len(got), got)
	}
	by := map[string]UpdateInfo{}
	for _, u := range got {
		by[u.Name] = u
	}
	ssl := by["openssl"]
	if !ssl.Security || ssl.Installed != "3.0.14-1~deb12u1" || ssl.Candidate != "3.0.15-1~deb12u1" || ssl.Arch != "amd64" {
		t.Errorf("openssl falsch gelesen: %+v", ssl)
	}
	if by["nginx"].Security {
		t.Errorf("nginx (updates) ist kein Sicherheitsupdate: %+v", by["nginx"])
	}
	if by["foo"].Archive != "ppa.example" {
		t.Errorf("Quelle von foo: %+v", by["foo"])
	}
}

func TestIsSecuritySuite(t *testing.T) {
	for suite, want := range map[string]bool{
		"bookworm-security": true, "jammy-security": true, "buster/updates": true, "stable-updates": false, "noble": false, "ppa.example": false,
	} {
		if isSecuritySuite(suite) != want {
			t.Errorf("%s: erwartet %v", suite, want)
		}
	}
}

const aptPolicyOut = `openssl:
  Installed: 3.0.14-1~deb12u1
  Candidate: 3.0.15-1~deb12u1
  Version table:
     3.0.15-1~deb12u1 500
        500 http://security.debian.org/debian-security bookworm-security/main amd64 Packages
 *** 3.0.14-1~deb12u1 100
        100 /var/lib/dpkg/status
foo:
  Installed: 1.0
  Candidate: 2.0
  Version table:
     2.0 500
        500 https://ppa.example.com/ubuntu jammy/main amd64 Packages
 *** 1.0 100
        100 /var/lib/dpkg/status
`

func TestParseAptPolicy(t *testing.T) {
	got := ParseAptPolicy(aptPolicyOut)
	if got["openssl"].URL != "http://security.debian.org/debian-security" || got["openssl"].Suite != "bookworm-security" {
		t.Errorf("openssl: %+v", got["openssl"])
	}
	if got["foo"].URL != "https://ppa.example.com/ubuntu" || got["foo"].Suite != "jammy" {
		t.Errorf("foo: %+v", got["foo"])
	}
}

func TestListFileBase(t *testing.T) {
	if got := listFileBase("http://security.debian.org/debian-security"); got != "security.debian.org_debian-security" {
		t.Errorf("listFileBase: %s", got)
	}
	if got := listFileBase("https://user:pw@host.example:8443/repo/"); got != "host.example%3a8443_repo" {
		t.Errorf("listFileBase mit Zugang: %s", got)
	}
}

func TestAptOrigin(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "security.debian.org_debian-security_dists_bookworm-security_InRelease")
	content := "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\nOrigin: Debian\nLabel: Debian-Security\nSuite: stable-security\n"
	if err := os.WriteFile(file, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := aptOrigin(dir, "http://security.debian.org/debian-security", "bookworm-security"); got != "Debian" {
		t.Errorf("Origin: %q", got)
	}
	if got := aptOrigin(dir, "http://nowhere.example/x", "stable"); got != "" {
		t.Errorf("unbekannte Quelle muss leer sein: %q", got)
	}
	if got := aptOrigin(dir, "http://security.debian.org/debian-security", "../etc"); got != "" {
		t.Errorf("Suite mit Pfadzeichen muss abgelehnt werden: %q", got)
	}
}

func TestOfficialOrigin(t *testing.T) {
	for origin, want := range map[string]bool{"Debian": true, "Ubuntu": true, "": false, "Docker": false, "nginx": false, "Google LLC": false} {
		if officialOrigin(origin) != want {
			t.Errorf("%q: erwartet %v", origin, want)
		}
	}
}

func TestParseAptSim(t *testing.T) {
	out := "NOTE: x\nInst libssl3 [3.0.14] (3.0.15 Debian-Security:12/stable-security [amd64])\nRemv oldlib [1.0]\nInst openssl [3.0.14] (3.0.15)\nConf openssl (3.0.15)\n"
	rem, inst := ParseAptSim(out)
	if strings.Join(rem, ",") != "oldlib" || strings.Join(inst, ",") != "libssl3,openssl" {
		t.Errorf("rem=%v inst=%v", rem, inst)
	}
}

const dnfOut = `
kernel-core.x86_64          5.14.0-503.14.1.el9_5      baseos
openssl.x86_64              1:3.2.2-6.el9_5.1          baseos
htop.x86_64                 3.3.0-1.el9                epel
Obsoleting Packages
old.x86_64                  1.0                        baseos
`

func TestParseDnfUpdateEntries(t *testing.T) {
	got := ParseDnfUpdateEntries(dnfOut)
	if len(got) != 3 {
		t.Fatalf("erwartet 3, erhalten %d: %+v", len(got), got)
	}
	by := map[string]UpdateInfo{}
	for _, u := range got {
		by[u.Name] = u
	}
	if !by["openssl"].Official || by["openssl"].Arch != "x86_64" || by["openssl"].Candidate != "1:3.2.2-6.el9_5.1" {
		t.Errorf("openssl: %+v", by["openssl"])
	}
	if by["htop"].Official {
		t.Errorf("epel ist keine Quelle der Distribution: %+v", by["htop"])
	}
}

func TestUpdateCandidatesNeedsPackageManager(t *testing.T) {
	old := PackageManager
	PackageManager = func() string { return "" }
	defer func() { PackageManager = old }()
	if _, err := Call(t.Context(), "update_candidates", Args{}); err == nil {
		t.Fatal("ohne Paketverwaltung muss ein Fehler kommen")
	}
}

func TestDnfCandidatesMarksSecurity(t *testing.T) {
	oldPM, oldRR := PackageManager, RootRead
	PackageManager = func() string { return PkgDnf }
	defer func() { PackageManager, RootRead = oldPM, oldRR }()
	var secAsked bool
	RootRead = func(_ context.Context, tool string, args Args) (string, error) {
		if tool != "pkg_check" {
			t.Fatalf("unerwartetes Werkzeug %s", tool)
		}
		if b, _ := args["security"].(bool); b {
			secAsked = true
			return "openssl.x86_64   1:3.2.2-6.el9_5.1   baseos\n", nil
		}
		return dnfOut, nil
	}
	raw, err := updateCandidates(t.Context(), Args{})
	if err != nil {
		t.Fatal(err)
	}
	var rep UpdateReport
	if err := json.Unmarshal([]byte(raw), &rep); err != nil {
		t.Fatalf("keine gültige Antwort: %v", err)
	}
	if !secAsked || rep.Manager != PkgDnf || len(rep.Updates) != 3 {
		t.Fatalf("Antwort: %+v", rep)
	}
	for _, u := range rep.Updates {
		if u.Security != (u.Name == "openssl") {
			t.Errorf("Sicherheitskennzeichen falsch bei %s", u.Name)
		}
	}
}
