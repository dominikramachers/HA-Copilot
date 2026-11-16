package tools

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolveExistingSymlinks(t *testing.T) {
	root := t.TempDir()
	realDir, _ := filepath.EvalSymlinks(root)
	_ = os.MkdirAll(filepath.Join(realDir, "a", "b"), 0o755)
	_ = os.WriteFile(filepath.Join(realDir, "a", "b", "f.txt"), []byte("x"), 0o644)
	_ = os.Symlink(filepath.Join(realDir, "a"), filepath.Join(realDir, "link"))
	got, err := ResolveExisting(filepath.Join(realDir, "link", "b", "f.txt"))
	if err != nil || got != filepath.Join(realDir, "a", "b", "f.txt") {
		t.Fatalf("got %q, %v", got, err)
	}
	got, err = ResolveExisting(filepath.Join(realDir, "a", "b", "..", "b", "f.txt"))
	if err != nil || got != filepath.Join(realDir, "a", "b", "f.txt") {
		t.Fatalf("dotdot: got %q, %v", got, err)
	}
	if _, err := ResolveExisting("relative/path"); err == nil {
		t.Error("relative path must fail")
	}
	if _, err := ResolveExisting(filepath.Join(realDir, "missing")); err == nil {
		t.Error("missing path must fail")
	}
	// loop of links
	_ = os.Symlink(filepath.Join(realDir, "l2"), filepath.Join(realDir, "l1"))
	_ = os.Symlink(filepath.Join(realDir, "l1"), filepath.Join(realDir, "l2"))
	if _, err := ResolveExisting(filepath.Join(realDir, "l1")); err == nil {
		t.Error("symlink loop must fail")
	}
	if got, err := ResolveExisting("/"); err != nil || got != "/" {
		t.Errorf("root: %q %v", got, err)
	}
}

func TestResolveParent(t *testing.T) {
	root, _ := filepath.EvalSymlinks(t.TempDir())
	_ = os.WriteFile(filepath.Join(root, "f.conf"), []byte("x"), 0o644)
	got, exists, err := ResolveParent(filepath.Join(root, "f.conf"))
	if err != nil || !exists || got != filepath.Join(root, "f.conf") {
		t.Fatalf("existing: %q %v %v", got, exists, err)
	}
	got, exists, err = ResolveParent(filepath.Join(root, "new.conf"))
	if err != nil || exists || got != filepath.Join(root, "new.conf") {
		t.Fatalf("new: %q %v %v", got, exists, err)
	}
	_ = os.Symlink(filepath.Join(root, "f.conf"), filepath.Join(root, "l.conf"))
	if _, _, err := ResolveParent(filepath.Join(root, "l.conf")); err == nil {
		t.Error("final symlink must fail")
	}
	for _, p := range []string{"", "rel", root + "/", root + "/../x", root + "//x", root + "/.hidden", root + "/a b", root + "/-rf", "/nonexistent-dir/x"} {
		if _, _, err := ResolveParent(p); err == nil {
			t.Errorf("%q must be refused", p)
		}
	}
}

func TestSensitivePath(t *testing.T) {
	for _, p := range []string{"/etc/shadow", "/home/u/.ssh/id_rsa", "/etc/copilot-agent/policy", "/etc/copilot-agent/key.pem", "/root/.bash_history", "/home/u/authorized_keys", "/etc/ssl/private/x.key", "/srv/x.p12", "/etc/nginx/.htpasswd"} {
		if !SensitivePath(p) {
			t.Errorf("%s must be sensitive", p)
		}
	}
	for _, p := range []string{"/etc/nginx/nginx.conf", "/var/log/syslog", "/etc/hostname"} {
		if SensitivePath(p) {
			t.Errorf("%s must not be sensitive", p)
		}
	}
}
