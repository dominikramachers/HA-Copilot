// copilot-agent: der Linux-Server-Agent für HA Copilot (Etappe 1: nur lesen).
//
//	copilot-agent enroll --hub host:8101 --key ck_… --ca-fingerprint sha256:… [--state-dir …] [--name …]
//	copilot-agent run [--state-dir …]
//	copilot-agent version
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/dominikramachers/ha-copilot/agent/internal/config"
	"github.com/dominikramachers/ha-copilot/agent/internal/hub"
)

// version wird beim Bau gesetzt (-ldflags "-X main.version=…").
var version = "dev"

const defaultStateDir = "/var/lib/copilot-agent"

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
	case "help", "--help", "-h":
		usage()
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, `copilot-agent – Linux-Server-Agent für HA Copilot

  copilot-agent enroll --hub host:8101 --key ck_… --ca-fingerprint sha256:… [--state-dir DIR] [--name NAME]
      Meldet diesen Server beim Hub an (der Schlüssel kann auch in COPILOT_AGENT_KEY stehen).
  copilot-agent run [--state-dir DIR]
      Verbindet sich mit dem Hub und bleibt verbunden.
  copilot-agent version`)
}

func enroll(args []string) int {
	fs := flag.NewFlagSet("enroll", flag.ExitOnError)
	hubAddr := fs.String("hub", "", "Adresse des Hubs (host:port)")
	key := fs.String("key", os.Getenv("COPILOT_AGENT_KEY"), "Registrierungsschlüssel (ck_…)")
	fingerprint := fs.String("ca-fingerprint", "", "Fingerabdruck der Hub-CA (sha256:…)")
	stateDir := fs.String("state-dir", defaultStateDir, "Zustandsverzeichnis")
	name := fs.String("name", "", "Anzeigename (Vorgabe: Hostname)")
	_ = fs.Parse(args)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	id, err := hub.Enroll(ctx, config.Dir(*stateDir), hub.EnrollOptions{
		Hub: *hubAddr, Key: *key, CAFingerprint: *fingerprint, Name: *name, Version: version,
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, "Anmeldung fehlgeschlagen:", err)
		return 1
	}
	fmt.Printf("Angemeldet als %s. Der Server erscheint in HA Copilot unter „Server“ als „Ausstehend“ und muss dort bestätigt werden.\n", id)
	return 0
}

func run(args []string) int {
	fs := flag.NewFlagSet("run", flag.ExitOnError)
	stateDir := fs.String("state-dir", defaultStateDir, "Zustandsverzeichnis")
	_ = fs.Parse(args)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	agent := &hub.Agent{Dir: config.Dir(*stateDir), Version: version}
	slog.Info("Agent startet", "version", version)
	if err := agent.Run(ctx); err != nil {
		fmt.Fprintln(os.Stderr, "Fehler:", err)
		return 1
	}
	return 0
}
