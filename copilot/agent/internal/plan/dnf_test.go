package plan

import (
	"context"
	"strings"
	"testing"

	"github.com/dominikramachers/ha-copilot/agent/internal/tools"
)

// withDnf lässt den Test so laufen, als wäre der Server ein Red-Hat-System.
func withDnf(t *testing.T) {
	t.Helper()
	old := tools.PackageManager
	tools.PackageManager = func() string { return tools.PkgDnf }
	t.Cleanup(func() { tools.PackageManager = old })
}

func TestDnfCommands(t *testing.T) {
	withDnf(t)
	cases := []struct {
		args  Args
		argv  string
		class int
		undo  string
	}{
		{Args{"action": "update"}, "dnf -y --refresh makecache", 1, ""},
		{Args{"action": "install", "packages": list("htop", "NetworkManager-tui")}, "dnf -y install htop NetworkManager-tui", 1, "dnf remove htop NetworkManager-tui"},
		{Args{"action": "remove", "packages": list("htop")}, "dnf -y remove htop", 2, "dnf install htop"},
		{Args{"action": "upgrade"}, "dnf -y upgrade", 2, ""},
		{Args{"action": "upgrade", "packages": list("openssl")}, "dnf -y upgrade openssl", 1, ""},
		{Args{"action": "install", "packages": list("libstdc++", "gcc-c++", "python3.12")}, "dnf -y install libstdc++ gcc-c++ python3.12", 1, ""},
	}
	for _, c := range cases {
		a, err := Classify(ToolPackage, c.args)
		if err != nil {
			t.Fatalf("%v: %v", c.args, err)
		}
		if a.Command != c.argv || a.Class != c.class || !a.Root || len(a.Env) != 0 {
			t.Errorf("%v: %q Stufe %d root=%v env=%v", c.args, a.Command, a.Class, a.Root, a.Env)
		}
		if c.undo != "" && a.Undo.Text != c.undo {
			t.Errorf("%v: Rückweg %q, erwartet %q", c.args, a.Undo.Text, c.undo)
		}
		if len(a.Check) > 0 && a.Check[0] != "rpm" {
			t.Errorf("%v: Prüfung nicht mit rpm: %v", c.args, a.Check)
		}
	}
	// Die Zusammenfassung nennt den Befehl der Paketverwaltung des Servers.
	a, _ := Classify(ToolPackage, Args{"action": "update"})
	if !strings.Contains(a.Summary.Text, "dnf makecache") || a.Summary.Params["command"] != "dnf makecache" {
		t.Errorf("Zusammenfassung: %+v", a.Summary)
	}
}

func TestDnfRejectsUnsafeNames(t *testing.T) {
	withDnf(t)
	for _, bad := range []string{"*", "foo*", "@development-tools", "-y", "a b", "a;b", "foo=1.0", "foo-1.0-1.x86_64 bar", "../x", ""} {
		if _, err := Classify(ToolPackage, Args{"action": "install", "packages": list(bad)}); err == nil {
			t.Errorf("%q müsste abgelehnt werden", bad)
		}
	}
}

func TestDnfProtectedPackages(t *testing.T) {
	withDnf(t)
	for _, name := range []string{"kernel-core", "kernel", "systemd", "systemd-libs", "glibc", "NetworkManager", "dnf", "rpm", "openssh-server", "sudo", "bash", "grub2-efi-x64", "selinux-policy-targeted", "shadow-utils", "firewalld", "fedora-release-common"} {
		a, err := Classify(ToolPackage, Args{"action": "remove", "packages": list("htop", name)})
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if a.Class != 3 {
			t.Errorf("%s: Stufe %d, erwartet 3", name, a.Class)
		}
	}
	a, _ := Classify(ToolPackage, Args{"action": "remove", "packages": list("htop", "nginx")})
	if a.Class != 2 {
		t.Errorf("gewöhnliche Pakete: Stufe %d", a.Class)
	}
}

func TestNoPackageManager(t *testing.T) {
	old := tools.PackageManager
	tools.PackageManager = func() string { return "" }
	defer func() { tools.PackageManager = old }()
	if _, err := Classify(ToolPackage, Args{"action": "update"}); err == nil || !strings.Contains(err.Error(), "no supported package manager") {
		t.Fatalf("Fehler erwartet: %v", err)
	}
}

func TestDnfSimulationArgv(t *testing.T) {
	withDnf(t)
	a, _ := Classify(ToolPackage, Args{"action": "install", "packages": list("htop")})
	got := strings.Join(SimulationArgv(a), " ")
	if got != "dnf --assumeno install htop" {
		t.Fatalf("Trockenlauf: %q", got)
	}
}

const dnf4Install = `Last metadata expiration check: 0:12:01 ago on Mon 16 Nov 2026 10:00:00.
Dependencies resolved.
================================================================================
 Package            Architecture   Version              Repository         Size
================================================================================
Installing:
 htop               x86_64         3.3.0-1.el9          epel              171 k
Installing dependencies:
 libnl3-cli-extra-
                    x86_64         3.9.0-1.el9          baseos            200 k
Installing weak dependencies:
 lm_sensors-libs    x86_64         3.6.0-10.el9         baseos             50 k
Upgrading:
 openssl-libs       x86_64         1:3.2.1-2.el9        baseos            2.3 M

Transaction Summary
================================================================================
Install  3 Packages
Upgrade  1 Package

Total download size: 2.7 M
Operation aborted.
`

const dnf5Remove = `Updating and loading repositories:
Repositories loaded.
Package                      Arch   Version                 Repository      Size
Removing:
 nginx                       x86_64 1:1.26.2-1.fc41         @System      2.2 MiB
Removing dependent packages:
 nginx-mod-http-image-filter x86_64 1:1.26.2-1.fc41         @System     50.0 KiB
Removing unused dependencies:
 systemd-libs                x86_64 256.7-1.fc41            @System      1.0 MiB

Transaction Summary:
 Removing:           3 packages

Operation aborted by the user.
`

func TestParseDnfSimulation(t *testing.T) {
	msg, removed := ParseDnfSimulation(dnf4Install)
	if len(removed) != 0 {
		t.Fatalf("nichts zu entfernen: %v", removed)
	}
	text := msg.FullText()
	for _, want := range []string{"4 package(s)", "htop", "libnl3-cli-extra-", "lm_sensors-libs", "openssl-libs"} {
		if !strings.Contains(text, want) {
			t.Errorf("%q fehlt in %q", want, text)
		}
	}
	if strings.Contains(text, "x86_64") || strings.Contains(text, "baseos") {
		t.Errorf("Spalten dürfen nicht als Pakete erscheinen: %q", text)
	}
	msg, removed = ParseDnfSimulation(dnf5Remove)
	if strings.Join(removed, ",") != "nginx,nginx-mod-http-image-filter,systemd-libs" {
		t.Fatalf("entfernt: %v", removed)
	}
	if !strings.Contains(msg.FullText(), "3 to remove") && !strings.Contains(msg.FullText(), "3 ") {
		t.Errorf("Kopfzeile: %q", msg.FullText())
	}
	// Fehler werden gezeigt
	msg, _ = ParseDnfSimulation("Last metadata expiration check: 0:00:01 ago\nError: Unable to find a match: nosuchpkg\n")
	if !strings.Contains(msg.FullText(), "Unable to find a match: nosuchpkg") {
		t.Errorf("Fehler fehlt: %q", msg.FullText())
	}
	// nichts zu tun
	msg, removed = ParseDnfSimulation("Dependencies resolved.\nNothing to do.\nComplete!\n")
	if len(removed) != 0 || !strings.Contains(msg.FullText(), "0 package(s)") {
		t.Errorf("nichts zu tun: %q", msg.FullText())
	}
}

func TestDnfPreviewGoesThroughTheHelper(t *testing.T) {
	withDnf(t)
	root := &fakeRoot{up: true, resp: Response{Output: dnf4Install}}
	m := NewManager(operate, root)
	p, err := m.Prepare(context.Background(), ToolPackage, Args{"action": "install", "packages": list("htop")})
	if err != nil {
		t.Fatal(err)
	}
	if len(root.calls) != 1 || root.calls[0].Tool != ToolPackageSim {
		t.Fatalf("Trockenlauf über den Helfer erwartet: %+v", root.calls)
	}
	if p.Class != 1 || p.Runner != "root" || !strings.Contains(p.Preview, "htop") {
		t.Fatalf("Plan: %+v", p)
	}
	// Würde der Trockenlauf ein Grundsystem-Paket entfernen, wird die Anfrage abgelehnt
	root = &fakeRoot{up: true, resp: Response{Output: dnf5Remove}}
	m = NewManager(operate, root)
	if _, err := m.Prepare(context.Background(), ToolPackage, Args{"action": "remove", "packages": list("nginx")}); err == nil || !strings.Contains(err.Error(), "systemd-libs") {
		t.Fatalf("Ablehnung erwartet: %v", err)
	}
	// Das Aktualisieren der Paketlisten braucht keinen Trockenlauf
	root = &fakeRoot{up: true}
	m = NewManager(operate, root)
	if _, err := m.Prepare(context.Background(), ToolPackage, Args{"action": "update"}); err != nil || len(root.calls) != 0 {
		t.Fatalf("update: %v %+v", err, root.calls)
	}
	// Ein Fehler des Helfers zeigt sich als Fehler der Vorschau
	root = &fakeRoot{up: true, resp: Response{Error: "dnf is not installed on this server"}}
	m = NewManager(operate, root)
	if _, err := m.Prepare(context.Background(), ToolPackage, Args{"action": "install", "packages": list("htop")}); err == nil || !strings.Contains(err.Error(), "dry run not possible") {
		t.Fatalf("Fehler erwartet: %v", err)
	}
}

func TestDnfReadCommands(t *testing.T) {
	read := [][]string{
		{"dnf", "list", "installed"}, {"dnf", "info", "htop"}, {"dnf", "-q", "repolist"}, {"dnf5", "search", "nginx"}, {"yum", "check-update"},
		{"rpm", "-qa"}, {"rpm", "-q", "htop"}, {"rpm", "-qi", "htop"}, {"rpm", "-V", "openssh-server"}, {"rpm", "--query", "--all"},
	}
	for _, argv := range read {
		if class, _ := argvClass(argv); class != 1 {
			t.Errorf("%v müsste lesend sein, Stufe %d", argv, class)
		}
	}
	write := [][]string{
		{"dnf", "install", "htop"}, {"dnf", "-y", "remove", "htop"}, {"dnf", "makecache"}, {"dnf", "history", "undo", "5"}, {"dnf", "upgrade"},
		{"rpm", "-i", "x.rpm"}, {"rpm", "-U", "x.rpm"}, {"rpm", "-e", "htop"}, {"rpm", "--eval", "%(id)"}, {"rpm", "-q", "--eval", "%(id)"},
		{"rpm", "--import", "key"}, {"rpm"},
	}
	for _, argv := range write {
		if class, _ := argvClass(argv); class < 2 {
			t.Errorf("%v darf nicht als lesend gelten (Stufe %d)", argv, class)
		}
	}
}
