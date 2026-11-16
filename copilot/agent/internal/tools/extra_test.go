package tools

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/dominikramachers/ha-copilot/agent/internal/metrics"
)

func TestFileReadHeadTailAndList(t *testing.T) {
	dir, _ := filepath.EvalSymlinks(t.TempDir())
	var lines []string
	for i := 1; i <= 500; i++ {
		lines = append(lines, "line "+strings.Repeat("x", i%3)+string(rune('a'+i%26)))
	}
	path := filepath.Join(dir, "big.log")
	_ = os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o644)
	out, err := fileRead(Args{"path": path, "lines": float64(5)})
	if err != nil || !strings.Contains(out, "first 5 lines") || strings.Count(out, "\nline ") != 5 {
		t.Fatalf("head: %v\n%s", err, out)
	}
	out, err = fileRead(Args{"path": path, "lines": float64(3), "from": "end"})
	if err != nil || !strings.Contains(out, "last 3 lines") || !strings.Contains(out, lines[499]) {
		t.Fatalf("tail: %v\n%s", err, out)
	}
	out, err = fileRead(Args{"path": dir})
	if err != nil || !strings.Contains(out, "directory, 1 entries") || !strings.Contains(out, "big.log") {
		t.Fatalf("list: %v\n%s", err, out)
	}
	if _, err := fileRead(Args{"path": path, "lines": "many"}); err == nil {
		t.Error("a non-numeric line count must be refused")
	}
	if _, err := fileRead(Args{}); err == nil {
		t.Error("missing path must be refused")
	}
}

func TestFileReadRefusesKeysAndBinary(t *testing.T) {
	dir, _ := filepath.EvalSymlinks(t.TempDir())
	_ = os.MkdirAll(filepath.Join(dir, ".ssh"), 0o700)
	secret := filepath.Join(dir, ".ssh", "id_ed25519")
	_ = os.WriteFile(secret, []byte("PRIVATE"), 0o600)
	if _, err := fileRead(Args{"path": secret}); err == nil || !strings.Contains(err.Error(), "confidential") {
		t.Errorf("secret must be refused, got %v", err)
	}
	// a symlink with a harmless name that points to a secret is refused as well
	link := filepath.Join(dir, "harmless.txt")
	_ = os.Symlink(secret, link)
	if _, err := fileRead(Args{"path": link}); err == nil {
		t.Error("link to a secret must be refused")
	}
	bin := filepath.Join(dir, "data.bin")
	_ = os.WriteFile(bin, []byte{1, 2, 0, 3}, 0o644)
	out, err := fileRead(Args{"path": bin})
	if err != nil || !strings.Contains(out, "binary") {
		t.Errorf("binary: %v %q", err, out)
	}
}

func TestDockerArgv(t *testing.T) {
	for _, what := range []string{"ps", "stats"} {
		if _, err := DockerArgv(Args{"what": what}); err != nil {
			t.Errorf("%s: %v", what, err)
		}
	}
	argv, err := DockerArgv(Args{"what": "logs", "container": "web-1", "lines": float64(20)})
	if err != nil || argv[0] != "docker" || argv[len(argv)-1] != "web-1" || argv[len(argv)-2] != "--" {
		t.Fatalf("logs: %v %v", argv, err)
	}
	inspect, _ := DockerArgv(Args{"what": "inspect", "container": "web-1"})
	if strings.Contains(strings.Join(inspect, " "), "Config.Env") {
		t.Error("inspect must not show environment variables")
	}
	for _, c := range []string{"", "-rf", "a b", "x;id", "$(id)", "../x", strings.Repeat("a", 200)} {
		if _, err := DockerArgv(Args{"what": "logs", "container": c}); err == nil {
			t.Errorf("container %q must be refused", c)
		}
	}
	for _, what := range []string{"", "exec", "run", "rm", "ps; id"} {
		if _, err := DockerArgv(Args{"what": what}); err == nil {
			t.Errorf("what %q must be refused", what)
		}
	}
}

func TestDockerNeedsRootHelper(t *testing.T) {
	old := RootRead
	defer func() { RootRead = old }()
	RootRead = nil
	if _, err := docker(context.Background(), Args{"what": "ps"}); err == nil {
		t.Error("without the helper docker must fail")
	}
	var got string
	RootRead = func(_ context.Context, tool string, _ Args) (string, error) { got = tool; return "ok", nil }
	if out, err := docker(context.Background(), Args{"what": "ps"}); err != nil || out != "ok" || got != "docker" {
		t.Errorf("docker via helper: %q %v %q", out, err, got)
	}
	// invalid arguments never reach the helper
	got = ""
	if _, err := docker(context.Background(), Args{"what": "exec"}); err == nil || got != "" {
		t.Error("invalid arguments must be refused before the helper")
	}
}

func TestMetricsHistoryTool(t *testing.T) {
	old := metrics.Default
	defer func() { metrics.Default = old }()
	metrics.Default = metrics.New()
	out, err := metricsHistory(Args{})
	if err != nil || !strings.Contains(out, "No metrics recorded") {
		t.Fatalf("empty: %v %q", err, out)
	}
	now := time.Now().Unix()
	for i := 0; i < 10; i++ {
		metrics.Default.Add(metrics.Sample{At: now - int64(10-i)*60, Load1: float64(i), MemPct: 50, DiskPct: 70})
	}
	out, err = metricsHistory(Args{"minutes": float64(30)})
	if err != nil || !strings.Contains(out, "10 samples") || !strings.Contains(out, "max 9.00") {
		t.Fatalf("report: %v\n%s", err, out)
	}
	if _, err := metricsHistory(Args{"minutes": "abc"}); err == nil {
		t.Error("non-numeric minutes must be refused")
	}
}

func TestPackageInfoRejectsBadNames(t *testing.T) {
	for _, p := range []string{"", "-y", "a b", "x;id", "$(id)", "../x", "A"} {
		if _, err := packageInfo(context.Background(), Args{"package": p}); err == nil {
			t.Errorf("package %q must be refused", p)
		}
	}
}
