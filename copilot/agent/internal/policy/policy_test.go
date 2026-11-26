package policy

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDefaultIsReadOnly(t *testing.T) {
	if Load(filepath.Join(t.TempDir(), "gibt-es-nicht")).Operate {
		t.Fatal("ohne Datei darf nichts geändert werden")
	}
}

func TestParse(t *testing.T) {
	p := Parse("# Kommentar\nki_access = operate   # ja\nmax_class=1\nrun_command=off\nroot=off\nunsinn\nmax_class=9\n")
	if !p.Operate || p.MaxClass != 1 || p.RunCommand || p.Root {
		t.Fatalf("unerwartet: %+v", p)
	}
	if q := Parse("ki_access=read\n"); q.Operate || q.MaxClass != 2 || !q.RunCommand || !q.Root {
		t.Fatalf("unerwartet: %+v", q)
	}
}

func TestLoadReadsFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "policy")
	if err := os.WriteFile(path, []byte("ki_access=operate\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if !Load(path).Operate {
		t.Fatal("operate nicht gelesen")
	}
}

func TestParseUpdateAndWritePaths(t *testing.T) {
	p := Parse("update=auto\nwrite_paths=/etc/nginx, /opt/app/ ,relative,/\nupdate_key=QUJD # Kommentar\n")
	if p.Update != UpdateAuto || p.UpdateKey != "QUJD" {
		t.Errorf("update=%q key=%q", p.Update, p.UpdateKey)
	}
	if len(p.WritePaths) != 2 || p.WritePaths[0] != "/etc/nginx" || p.WritePaths[1] != "/opt/app" {
		t.Errorf("write_paths=%v", p.WritePaths)
	}
	if d := Parse(""); d.Update != UpdateManual || len(d.WritePaths) == 0 {
		t.Errorf("defaults: %+v", d)
	}
	if p := Parse("update=sometimes"); p.Update != UpdateManual {
		t.Errorf("invalid update value must keep the default, got %q", p.Update)
	}
	if p := Parse("write_paths="); len(p.WritePaths) != 0 {
		t.Errorf("empty write_paths means nowhere, got %v", p.WritePaths)
	}
	allowed := Parse("write_paths=/etc/nginx")
	if !allowed.WriteAllowed("/etc/nginx/conf.d/a.conf") || allowed.WriteAllowed("/etc/nginx-evil/a.conf") || allowed.WriteAllowed("/etc/passwd") {
		t.Error("WriteAllowed must match whole directories only")
	}
}

func TestParseAutoUpdate(t *testing.T) {
	if Parse("").AutoUpdateDeny {
		t.Error("ohne Angabe ist die automatische Aktualisierung nicht gesperrt")
	}
	if !Parse("auto_update=deny").AutoUpdateDeny || !Parse("auto_update = OFF # nie").AutoUpdateDeny {
		t.Error("auto_update=deny/off muss sperren")
	}
	if Parse("auto_update=allow").AutoUpdateDeny || Parse("auto_update=quatsch").AutoUpdateDeny {
		t.Error("andere Werte sperren nicht")
	}
}
