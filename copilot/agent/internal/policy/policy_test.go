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
