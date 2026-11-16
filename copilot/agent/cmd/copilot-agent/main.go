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
	"strconv"
	"syscall"

	"github.com/dominikramachers/ha-copilot/agent/internal/config"
	"github.com/dominikramachers/ha-copilot/agent/internal/helper"
	"github.com/dominikramachers/ha-copilot/agent/internal/hub"
	"github.com/dominikramachers/ha-copilot/agent/internal/plan"
	"github.com/dominikramachers/ha-copilot/agent/internal/policy"
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
	fmt.Fprintln(os.Stderr, `copilot-agent – Linux-Server-Agent für HA Copilot

  copilot-agent enroll --hub host:8101 --key ck_… --ca-fingerprint sha256:… [--state-dir DIR] [--name NAME]
      Meldet diesen Server beim Hub an (der Schlüssel kann auch in COPILOT_AGENT_KEY stehen).
  copilot-agent run [--state-dir DIR] [--policy DATEI] [--helper-socket PFAD]
      Verbindet sich mit dem Hub und bleibt verbunden.
  copilot-agent helper [--policy DATEI] [--socket PFAD]
      Root-Helfer für Änderungen nach Freigabe (läuft als eigene Systemd-Einheit, nicht von Hand starten).
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
	policyPath := fs.String("policy", policy.DefaultPath, "lokale Richtlinie (fehlt die Datei, kann der Agent nur lesen)")
	socket := fs.String("helper-socket", helper.DefaultSocket, "Socket des Root-Helfers")
	_ = fs.Parse(args)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	load := func() policy.Policy { return policy.Load(*policyPath) }
	manager := plan.NewManager(load, &helper.Client{Socket: *socket})
	agent := &hub.Agent{Dir: config.Dir(*stateDir), Version: version, Changes: manager}
	slog.Info("Agent startet", "version", version, "richtlinie", *policyPath)
	if err := agent.Run(ctx); err != nil {
		fmt.Fprintln(os.Stderr, "Fehler:", err)
		return 1
	}
	return 0
}

// runHelper ist der Root-Helfer. Er nimmt nur Anfragen von root und vom Agenten-Benutzer an.
func runHelper(args []string) int {
	fs := flag.NewFlagSet("helper", flag.ExitOnError)
	policyPath := fs.String("policy", policy.DefaultPath, "lokale Richtlinie")
	socket := fs.String("socket", helper.DefaultSocket, "Socket-Pfad")
	agentUser := fs.String("agent-user", "copilot-agent", "Benutzer des Agenten (Gruppe gleichen Namens bekommt Zugriff auf den Socket)")
	_ = fs.Parse(args)
	if os.Geteuid() != 0 {
		fmt.Fprintln(os.Stderr, "Der Helfer muss als root laufen (Systemd-Einheit copilot-helper.service).")
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
	slog.Info("Helfer startet", "version", version, "socket", *socket, "agent_uid", uid)
	err := helper.Serve(ctx, helper.Options{
		Socket: *socket, AllowUID: uid, GroupName: *agentUser,
		Policy: func() policy.Policy { return policy.Load(*policyPath) },
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, "Fehler:", err)
		return 1
	}
	return 0
}
