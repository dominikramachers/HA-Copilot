package update

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
)

func TestNewerAndParse(t *testing.T) {
	cases := []struct {
		offered, current string
		want             bool
	}{
		{"0.61.0", "0.60.8", true}, {"0.60.9", "0.60.8", true}, {"1.0.0", "0.99.99", true}, {"v0.61.0", "0.60.8", true},
		{"0.60.8", "0.60.8", false}, {"0.60.7", "0.60.8", false}, {"0.10.0", "0.9.0", true},
		{"dev", "0.60.8", false}, {"0.61.0", "dev", false}, {"", "", false}, {"0.61", "0.60.8", false}, {"0.61.0-rc1", "0.60.8", false},
		{"0.061.0", "0.60.8", false},
	}
	for _, c := range cases {
		if got := Newer(c.offered, c.current); got != c.want {
			t.Errorf("Newer(%q,%q)=%v, want %v", c.offered, c.current, got, c.want)
		}
	}
}

func TestOfferValid(t *testing.T) {
	good := Offer{Version: "0.61.0", SHA256: strings.Repeat("a", 64), Size: 1000}
	if !good.Valid() {
		t.Error("good offer rejected")
	}
	for _, o := range []Offer{
		{Version: "dev", SHA256: good.SHA256, Size: 1}, {Version: "0.61.0", SHA256: "abc", Size: 1}, {Version: "0.61.0", SHA256: strings.Repeat("z", 64), Size: 1},
		{Version: "0.61.0", SHA256: good.SHA256, Size: 0}, {Version: "0.61.0", SHA256: good.SHA256, Size: MaxSize + 1},
	} {
		if o.Valid() {
			t.Errorf("offer %+v must be invalid", o)
		}
	}
}

func TestVerifySig(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	sum := strings.Repeat("ab", 32)
	sig := base64.StdEncoding.EncodeToString(ed25519.Sign(priv, SigMessage("0.61.0", "amd64", sum)))
	key := base64.StdEncoding.EncodeToString(pub)
	if err := VerifySig(key, "0.61.0", "amd64", sum, sig); err != nil {
		t.Fatal(err)
	}
	for name, err := range map[string]error{
		"other version": VerifySig(key, "0.61.1", "amd64", sum, sig),
		"other arch":    VerifySig(key, "0.61.0", "arm64", sum, sig),
		"other hash":    VerifySig(key, "0.61.0", "amd64", strings.Repeat("cd", 32), sig),
		"no signature":  VerifySig(key, "0.61.0", "amd64", sum, ""),
		"bad signature": VerifySig(key, "0.61.0", "amd64", sum, "AAAA"),
		"bad key":       VerifySig("nope", "0.61.0", "amd64", sum, sig),
	} {
		if err == nil {
			t.Errorf("%s must fail", name)
		}
	}
	other, _, _ := ed25519.GenerateKey(rand.Reader)
	if VerifySig(base64.StdEncoding.EncodeToString(other), "0.61.0", "amd64", sum, sig) == nil {
		t.Error("a signature from another key must fail")
	}
}

func fakeBinary(t *testing.T, dir, version string) (string, Offer) {
	t.Helper()
	body := "#!/bin/sh\n[ \"$1\" = version ] && echo " + version + "\n# padding " + strings.Repeat("x", 200) + "\n"
	path := filepath.Join(dir, "fake-"+version)
	if err := os.WriteFile(path, []byte(body), 0o755); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256([]byte(body))
	return path, Offer{Version: version, SHA256: hex.EncodeToString(sum[:]), Size: int64(len(body))}
}

func TestDownloadChecksAndSelfTest(t *testing.T) {
	dir := t.TempDir()
	src, offer := fakeBinary(t, dir, "0.61.0")
	data, _ := os.ReadFile(src)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/bad" {
			_, _ = w.Write([]byte("something else entirely"))
			return
		}
		if r.URL.Path == "/missing" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write(data)
	}))
	defer srv.Close()
	dst := filepath.Join(dir, "got")
	if err := Download(context.Background(), srv.Client(), srv.URL+"/ok", dst, offer); err != nil {
		t.Fatal(err)
	}
	if info, err := os.Stat(dst); err != nil || info.Mode().Perm() != 0o700 {
		t.Fatalf("downloaded file: %v %v", info, err)
	}
	if err := SelfTest(context.Background(), dst, "0.61.0"); err != nil {
		t.Fatal(err)
	}
	if err := SelfTest(context.Background(), dst, "0.62.0"); err == nil {
		t.Error("a wrong reported version must fail the self test")
	}
	if err := Download(context.Background(), srv.Client(), srv.URL+"/bad", dst, offer); err == nil {
		t.Error("wrong content must fail")
	}
	if _, err := os.Stat(dst); err == nil {
		t.Error("a failed download must not leave a file")
	}
	if err := Download(context.Background(), srv.Client(), srv.URL+"/missing", dst, offer); err == nil {
		t.Error("404 must fail")
	}
	wrong := offer
	wrong.SHA256 = strings.Repeat("0", 64)
	if err := Download(context.Background(), srv.Client(), srv.URL+"/ok", dst, wrong); err == nil {
		t.Error("checksum mismatch must fail")
	}
	short := offer
	short.Size--
	if err := Download(context.Background(), srv.Client(), srv.URL+"/ok", dst, short); err == nil {
		t.Error("size mismatch must fail")
	}
}

type env struct {
	in       *Installer
	bin      string
	restarts atomic.Int32
	dogs     atomic.Int32
	cancels  atomic.Int32
	state    string
	pol      string
}

func newEnv(t *testing.T) *env {
	t.Helper()
	root := t.TempDir()
	e := &env{state: filepath.Join(root, "state"), pol: filepath.Join(root, "policy")}
	_ = os.MkdirAll(filepath.Join(e.state, "update"), 0o700)
	_ = os.MkdirAll(e.pol, 0o755)
	oldBin, _ := fakeBinary(t, root, "0.60.8")
	e.bin = filepath.Join(root, "copilot-agent")
	data, _ := os.ReadFile(oldBin)
	_ = os.WriteFile(e.bin, data, 0o755)
	e.in = &Installer{
		Bin: e.bin, Dir: e.pol, StateDir: e.state, AgentUID: os.Getuid(), Current: "0.60.8", Arch: "amd64",
		Restart:        func() { e.restarts.Add(1) },
		Watchdog:       func(time.Duration, string) { e.dogs.Add(1) },
		CancelWatchdog: func() { e.cancels.Add(1) },
	}
	return e
}

func (e *env) stage(t *testing.T, version string) Offer {
	t.Helper()
	src, offer := fakeBinary(t, t.TempDir(), version)
	data, _ := os.ReadFile(src)
	if err := os.WriteFile(StagedPath(e.state), data, 0o700); err != nil {
		t.Fatal(err)
	}
	return offer
}

func version(t *testing.T, path string) string {
	t.Helper()
	data, _ := os.ReadFile(path)
	for _, l := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(l, "[ \"$1\" = version ] && echo ") {
			return strings.TrimPrefix(l, "[ \"$1\" = version ] && echo ")
		}
	}
	return ""
}

func TestInstallConfirmAndRollback(t *testing.T) {
	e := newEnv(t)
	pol := policy.Default()
	offer := e.stage(t, "0.61.0")
	out, err := e.in.Install(pol, Request{Offer: offer})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "0.61.0") || version(t, e.bin) != "0.61.0" || version(t, e.bin+prevSuffix) != "0.60.8" {
		t.Fatalf("install: %q now=%q prev=%q", out, version(t, e.bin), version(t, e.bin+prevSuffix))
	}
	if e.restarts.Load() != 1 || e.dogs.Load() != 1 {
		t.Errorf("restart=%d watchdog=%d", e.restarts.Load(), e.dogs.Load())
	}
	if _, err := os.Stat(StagedPath(e.state)); err == nil {
		t.Error("the staged file must be removed")
	}
	// while the update waits for confirmation no further update is accepted
	offer2 := e.stage(t, "0.62.0")
	if _, err := e.in.Install(pol, Request{Offer: offer2}); err == nil {
		t.Error("a second update while one is pending must be refused")
	}
	// the new agent reaches the hub: confirmed
	e.in.Confirm()
	if e.cancels.Load() != 1 {
		t.Error("the watchdog must be cancelled on confirmation")
	}
	if _, err := os.Stat(filepath.Join(e.pol, pendingName)); err == nil {
		t.Error("the pending marker must be gone")
	}
}

func TestRollbackWhenNotConfirmed(t *testing.T) {
	e := newEnv(t)
	offer := e.stage(t, "0.61.0")
	e.in.Now = func() time.Time { return time.Now().Add(-time.Hour) } // deadline lies in the past
	if _, err := e.in.Install(policy.Default(), Request{Offer: offer}); err != nil {
		t.Fatal(err)
	}
	e.in.Now = nil
	e.in.Recover()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if f := e.in.LastFailure(); f != nil {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	f := e.in.LastFailure()
	if f == nil || f.Version != "0.61.0" {
		t.Fatalf("failure note missing: %+v", f)
	}
	if version(t, e.bin) != "0.60.8" {
		t.Errorf("the old version must be back, have %q", version(t, e.bin))
	}
	if e.restarts.Load() < 2 {
		t.Error("the rollback must restart the agent")
	}
	// the same version is not tried again; a newer one is
	e.stage(t, "0.61.0")
	if _, err := e.in.Install(policy.Default(), Request{Offer: offer}); err == nil || !strings.Contains(err.Error(), "rolled back") {
		t.Errorf("a rolled back version must be refused, got %v", err)
	}
	if got := ReadFailure(e.pol); got == nil || got.Version != "0.61.0" {
		t.Errorf("ReadFailure: %+v", got)
	}
}

func TestInstallRefusals(t *testing.T) {
	signedPub, signedPriv, _ := ed25519.GenerateKey(rand.Reader)
	e := newEnv(t)
	offer := e.stage(t, "0.61.0")
	off, manual, auto := policy.Default(), policy.Default(), policy.Default()
	off.Update, auto.Update = policy.UpdateOff, policy.UpdateAuto
	if _, err := e.in.Install(off, Request{Offer: offer}); err == nil {
		t.Error("update=off must refuse")
	}
	if _, err := e.in.Install(manual, Request{Offer: offer, Auto: true}); err == nil {
		t.Error("an automatic update needs update=auto")
	}
	if _, err := e.in.Install(manual, Request{Offer: Offer{Version: "0.61.0", SHA256: "x", Size: 1}}); err == nil {
		t.Error("an invalid offer must refuse")
	}
	old := offer
	old.Version = "0.60.8"
	if _, err := e.in.Install(manual, Request{Offer: old}); err == nil {
		t.Error("the same version must refuse")
	}
	wrongSum := offer
	wrongSum.SHA256 = strings.Repeat("1", 64)
	if _, err := e.in.Install(manual, Request{Offer: wrongSum}); err == nil || !strings.Contains(err.Error(), "checksum") {
		t.Errorf("a wrong checksum must refuse, got %v", err)
	}
	if version(t, e.bin) != "0.60.8" || e.restarts.Load() != 0 {
		t.Error("a refused update must change nothing")
	}
	// the file is wrong although the offer is fine: the self test refuses it
	body := "#!/bin/sh\necho 9.9.9\n" + strings.Repeat("#", 100) + "\n"
	_ = os.WriteFile(StagedPath(e.state), []byte(body), 0o700)
	sum := sha256.Sum256([]byte(body))
	liar := Offer{Version: "0.61.0", SHA256: hex.EncodeToString(sum[:]), Size: int64(len(body))}
	if _, err := e.in.Install(manual, Request{Offer: liar}); err == nil || !strings.Contains(err.Error(), "reports version") {
		t.Errorf("a program with another version must refuse, got %v", err)
	}
	if version(t, e.bin) != "0.60.8" {
		t.Error("the installed program must stay")
	}
	// a signature is required once update_key is set
	keyed := auto
	keyed.UpdateKey = base64.StdEncoding.EncodeToString(signedPub)
	offer = e.stage(t, "0.61.0")
	if _, err := e.in.Install(keyed, Request{Offer: offer}); err == nil {
		t.Error("an unsigned update must refuse with update_key")
	}
	offer.Sig = base64.StdEncoding.EncodeToString(ed25519.Sign(signedPriv, SigMessage("0.61.0", "amd64", offer.SHA256)))
	if _, err := e.in.Install(keyed, Request{Offer: offer, Auto: true}); err != nil {
		t.Errorf("a correctly signed update must install: %v", err)
	}
}

func TestInstallRefusesForeignOrLinkedStagedFile(t *testing.T) {
	e := newEnv(t)
	offer := e.stage(t, "0.61.0")
	// a symbolic link in place of the staged file
	real := filepath.Join(t.TempDir(), "other")
	data, _ := os.ReadFile(StagedPath(e.state))
	_ = os.WriteFile(real, data, 0o700)
	_ = os.Remove(StagedPath(e.state))
	_ = os.Symlink(real, StagedPath(e.state))
	if _, err := e.in.Install(policy.Default(), Request{Offer: offer}); err == nil {
		t.Error("a symbolic link must be refused")
	}
	// a file owned by somebody else
	_ = os.Remove(StagedPath(e.state))
	_ = os.WriteFile(StagedPath(e.state), data, 0o700)
	e.in.AgentUID = os.Getuid() + 12345
	if os.Getuid() != 0 { // root owns everything, so this check only applies to normal users
		if _, err := e.in.Install(policy.Default(), Request{Offer: offer}); err == nil {
			t.Error("a file owned by another user must be refused")
		}
	}
}
