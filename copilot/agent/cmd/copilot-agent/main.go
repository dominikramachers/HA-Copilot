// copilot-agent: der Linux-Server-Agent für HA Copilot (lesen; ändern nur nach Freigabe und nur, wenn die lokale Richtlinie es erlaubt).
//
//	copilot-agent enroll --hub host:8101 --key ck_… --ca-fingerprint sha256:… [--state-dir …] [--name …]
//	copilot-agent run [--state-dir …] [--policy …] [--helper-socket …]
//	copilot-agent helper [--policy …] [--socket …]
//	copilot-agent version
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"os/user"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/dominikramachers/ha-copilot/agent/internal/collect"
	"github.com/dominikramachers/ha-copilot/agent/internal/config"
	"github.com/dominikramachers/ha-copilot/agent/internal/helper"
	"github.com/dominikramachers/ha-copilot/agent/internal/hub"
	"github.com/dominikramachers/ha-copilot/agent/internal/metrics"
	"github.com/dominikramachers/ha-copilot/agent/internal/plan"
	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
	"github.com/dominikramachers/ha-copilot/agent/internal/tools"
	"github.com/dominikramachers/ha-copilot/agent/internal/update"
)

// version wird beim Bau gesetzt (-ldflags "-X main.version=…").
var version = "dev"

const (
	defaultStateDir = "/var/lib/copilot-agent"
	defaultBin      = "/usr/local/bin/copilot-agent"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo})))
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "version", "--version", "-v":
		fmt.Println(version)
	case "enroll":
		os.Exit(enroll(os.Args[2:]))
	case "run":
		os.Exit(run(os.Args[2:]))
	case "helper":
		os.Exit(runHelper(os.Args[2:]))
	case "help", "--help", "-h":
		usage()
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, `copilot-agent - Linux server agent for HA Copilot

  copilot-agent enroll --hub host:8101 --key ck_... --ca-fingerprint sha256:... [--state-dir DIR] [--name NAME]
      Registers this server with the hub (the key can also be given in COPILOT_AGENT_KEY).
  copilot-agent run [--state-dir DIR] [--policy FILE] [--helper-socket PATH]
      Connects to the hub and stays connected.
  copilot-agent helper [--policy FILE] [--socket PATH] [--state-dir DIR] [--bin FILE]
      Root helper for changes after approval (runs as its own systemd unit, do not start it by hand).
  copilot-agent version`)
}

func enroll(args []string) int {
	fs := flag.NewFlagSet("enroll", flag.ExitOnError)
	hubAddr := fs.String("hub", "", "address of the hub (host:port)")
	key := fs.String("key", os.Getenv("COPILOT_AGENT_KEY"), "registration key (ck_...)")
	fingerprint := fs.String("ca-fingerprint", "", "fingerprint of the hub CA (sha256:...)")
	stateDir := fs.String("state-dir", defaultStateDir, "state directory")
	name := fs.String("name", "", "display name (default: hostname)")
	_ = fs.Parse(args)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	id, err := hub.Enroll(ctx, config.Dir(*stateDir), hub.EnrollOptions{
		Hub: *hubAddr, Key: *key, CAFingerprint: *fingerprint, Name: *name, Version: version,
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, "Enrollment failed:", err)
		return 1
	}
	fmt.Printf("Enrolled as %s. The server now appears in HA Copilot under Servers as \"Pending\" and has to be confirmed there.\n", id)
	return 0
}

func run(args []string) int {
	fs := flag.NewFlagSet("run", flag.ExitOnError)
	stateDir := fs.String("state-dir", defaultStateDir, "state directory")
	policyPath := fs.String("policy", policy.DefaultPath, "local policy (without the file the agent can only read)")
	socket := fs.String("helper-socket", helper.DefaultSocket, "socket of the root helper")
	_ = fs.Parse(args)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	load := func() policy.Policy { return policy.Load(*policyPath) }
	client := &helper.Client{Socket: *socket}
	manager := plan.NewManager(load, client)
	tools.RootRead = client.RootRead()
	metrics.Default.Load(tools.MetricsPath(*stateDir))
	go recordMetrics(ctx, *stateDir)
	agent := &hub.Agent{Dir: config.Dir(*stateDir), Version: version, Changes: manager, PolicyDir: filepath.Dir(*policyPath)}
	slog.Info("agent starting", "version", version, "policy", *policyPath)
	if err := agent.Run(ctx); err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return 1
	}
	return 0
}

// runHelper ist der Root-Helfer. Er nimmt nur Anfragen von root und vom Agenten-Benutzer an.
func runHelper(args []string) int {
	fs := flag.NewFlagSet("helper", flag.ExitOnError)
	policyPath := fs.String("policy", policy.DefaultPath, "local policy")
	socket := fs.String("socket", helper.DefaultSocket, "socket path")
	stateDir := fs.String("state-dir", defaultStateDir, "state directory of the agent (where it stages updates)")
	binPath := fs.String("bin", defaultBin, "installed program file (replaced by updates)")
	agentUser := fs.String("agent-user", "copilot-agent", "user of the agent (the group of the same name may access the socket)")
	_ = fs.Parse(args)
	if os.Geteuid() != 0 {
		fmt.Fprintln(os.Stderr, "The helper has to run as root (systemd unit copilot-helper.service).")
		return 1
	}
	uid := -1
	if u, err := user.Lookup(*agentUser); err == nil {
		if n, err := strconv.Atoi(u.Uid); err == nil {
			uid = n
		}
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	slog.Info("helper starting", "version", version, "socket", *socket, "agent_uid", uid)
	dir := filepath.Dir(*policyPath)
	installer := &update.Installer{
		Bin: *binPath, Dir: dir, StateDir: *stateDir, AgentUID: uid, Current: version, Arch: runtime.GOARCH,
		Restart: restartServices, Watchdog: scheduleRollback(*binPath, dir), CancelWatchdog: cancelRollback,
	}
	installer.Recover()
	err := helper.Serve(ctx, helper.Options{
		Socket: *socket, AllowUID: uid, GroupName: *agentUser, Installer: installer,
		Policy: func() policy.Policy { return policy.Load(*policyPath) },
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return 1
	}
	return 0
}

// recordMetrics füllt den Verlauf der Messwerte (jede Minute ein Punkt) und speichert ihn regelmäßig.
func recordMetrics(ctx context.Context, stateDir string) {
	path := tools.MetricsPath(stateDir)
	tick := time.NewTicker(metrics.Step)
	defer tick.Stop()
	save := time.NewTicker(tools.SaveEvery)
	defer save.Stop()
	metrics.Default.Add(collect.Sample())
	for {
		select {
		case <-ctx.Done():
			_ = metrics.Default.Save(path)
			return
		case <-tick.C:
			metrics.Default.Add(collect.Sample())
		case <-save.C:
			_ = metrics.Default.Save(path)
		}
	}
}

// restartServices startet Agent und Helfer kurz nach der Antwort neu (der Helfer startet sich dabei selbst neu).
func restartServices() {
	go func() {
		time.Sleep(1500 * time.Millisecond)
		_, _, _ = tools.RunWith(context.Background(), tools.Opts{Timeout: 20 * time.Second}, "systemctl", "restart", "--no-block", "copilot-agent.service", "copilot-helper.service")
	}()
}

const rollbackUnit = "copilot-agent-rollback"

// scheduleRollback plant einen vom Helfer unabhängigen Rücksetzer (systemd-Zeitgeber): Läuft die neue Fassung gar nicht an, setzt
// er nach der Frist die vorherige Datei zurück.
func scheduleRollback(bin, dir string) func(time.Duration, string) {
	return func(after time.Duration, version string) {
		script := fmt.Sprintf("if [ -e %[2]s/update-pending ] && [ -e %[1]s.prev ]; then mv -f %[1]s.prev %[1]s; rm -f %[2]s/update-pending; "+
			"printf '{\"version\":\"%[3]s\",\"at\":%%s,\"reason\":\"rolled back by the watchdog\"}' \"$(date +%%s)\" > %[2]s/update-failed; "+
			"systemctl restart copilot-helper.service copilot-agent.service; fi", bin, dir, strings.Map(func(r rune) rune {
			if (r >= '0' && r <= '9') || r == '.' {
				return r
			}
			return -1
		}, version))
		_, _, _ = tools.RunWith(context.Background(), tools.Opts{Timeout: 15 * time.Second}, "systemd-run", "--unit", rollbackUnit,
			fmt.Sprintf("--on-active=%ds", int(after.Seconds())), "--timer-property=AccuracySec=1s", "/bin/sh", "-c", script)
	}
}

func cancelRollback() {
	_, _, _ = tools.RunWith(context.Background(), tools.Opts{Timeout: 15 * time.Second}, "systemctl", "stop", rollbackUnit+".timer", rollbackUnit+".service")
}
