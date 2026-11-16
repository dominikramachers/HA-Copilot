package tools

import (
	"context"
	"strings"
	"testing"
)

func TestValidPackageName(t *testing.T) {
	good := map[string][]string{
		PkgApt: {"htop", "libstdc++6", "python3.12", "libc6:amd64"},
		PkgDnf: {"htop", "NetworkManager-tui", "libstdc++", "gcc-c++", "python3.12", "GConf2", "perl-Digest_SHA"},
	}
	for manager, names := range good {
		for _, n := range names {
			if !ValidPackageName(manager, n) {
				t.Errorf("%s: %q müsste gültig sein", manager, n)
			}
		}
	}
	bad := map[string][]string{
		PkgApt: {"Htop", "-y", "a b", "a;b", "htop=1", ""},
		PkgDnf: {"*", "foo*", "@group", "-y", "a b", "a;b", "foo=1", "libc6:amd64", ""},
	}
	for manager, names := range bad {
		for _, n := range names {
			if ValidPackageName(manager, n) {
				t.Errorf("%s: %q muss abgelehnt werden", manager, n)
			}
		}
	}
}

func TestParseDnfUpdates(t *testing.T) {
	out := `
kernel-core.x86_64                     5.14.0-427.el9              baseos
openssl-libs.x86_64                    1:3.2.1-2.el9               baseos
Security: kernel-core-5.14.0-362.el9.x86_64 is an installed security update

Obsoleting Packages
foo.x86_64                             2.0-1.el9                   appstream
    bar.x86_64                         1.0-1.el9                   @baseos
`
	got := ParseDnfUpdates(out)
	if len(got) != 2 || !strings.HasPrefix(got[0], "kernel-core.x86_64") {
		t.Fatalf("Aktualisierungen: %v", got)
	}
	if len(ParseDnfUpdates("Repositories loaded.\n")) != 0 || len(ParseDnfUpdates("")) != 0 {
		t.Fatal("ohne Aktualisierungen darf nichts gezählt werden")
	}
}

func TestDnfUpdatesNeedTheHelper(t *testing.T) {
	old, oldRead := PackageManager, RootRead
	PackageManager = func() string { return PkgDnf }
	defer func() { PackageManager, RootRead = old, oldRead }()
	RootRead = nil
	if _, err := DnfUpdates(context.Background()); err == nil {
		t.Fatal("ohne Helfer ist die Zahl unbekannt")
	}
	var asked string
	RootRead = func(_ context.Context, tool string, _ Args) (string, error) {
		asked = tool
		return "openssl-libs.x86_64   1:3.2.1-2.el9   baseos\n", nil
	}
	got, err := DnfUpdates(context.Background())
	if err != nil || len(got) != 1 || asked != "pkg_check" {
		t.Fatalf("%v %v %q", got, err, asked)
	}
}

func TestPackageInfoForDnfChecksTheName(t *testing.T) {
	old := PackageManager
	PackageManager = func() string { return PkgDnf }
	defer func() { PackageManager = old }()
	if _, err := packageInfo(context.Background(), Args{"package": "foo*"}); err == nil || !strings.Contains(err.Error(), "wildcard") {
		t.Fatalf("Platzhalter müssen abgelehnt werden: %v", err)
	}
}
