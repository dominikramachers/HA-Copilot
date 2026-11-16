// copilot-sign signiert die Agenten-Programme beim Veröffentlichen (GitHub Actions) und prüft die Signatur beim Bauen des Add-ons.
//
//	copilot-sign pub                                       öffentlicher Schlüssel (Base64) aus COPILOT_SIGNING_KEY
//	copilot-sign sign   -version V -arch A -file F         Signatur (Base64) auf der Standardausgabe; Schlüssel aus COPILOT_SIGNING_KEY
//	copilot-sign verify -pub DATEI -version V -arch A -file F -sig DATEI
//
// COPILOT_SIGNING_KEY enthält den privaten Schlüssel (PEM, PKCS#8). Er wird nie ausgegeben.
package main

import (
	"crypto/ed25519"
	"flag"
	"fmt"
	"os"
	"strings"

	"github.com/dominikramachers/ha-copilot/agent/internal/signing"
)

func main() {
	if len(os.Args) < 2 {
		fail("usage: copilot-sign pub | sign | verify")
	}
	switch os.Args[1] {
	case "pub":
		priv := privateKey()
		fmt.Println(signing.PublicBase64(priv))
	case "sign":
		fs := flag.NewFlagSet("sign", flag.ExitOnError)
		version := fs.String("version", "", "agent version, e.g. 0.61.0")
		arch := fs.String("arch", "", "amd64 or arm64")
		file := fs.String("file", "", "program file")
		_ = fs.Parse(os.Args[2:])
		need(*version, *arch, *file)
		sha, err := signing.FileSHA256(*file)
		if err != nil {
			fail(err.Error())
		}
		fmt.Println(signing.Sign(privateKey(), *version, *arch, sha))
	case "verify":
		fs := flag.NewFlagSet("verify", flag.ExitOnError)
		pub := fs.String("pub", "", "file with the public key (base64)")
		version := fs.String("version", "", "agent version")
		arch := fs.String("arch", "", "amd64 or arm64")
		file := fs.String("file", "", "program file")
		sig := fs.String("sig", "", "file with the signature (base64)")
		_ = fs.Parse(os.Args[2:])
		need(*version, *arch, *file, *pub, *sig)
		pubText, err := os.ReadFile(*pub)
		if err != nil {
			fail(err.Error())
		}
		sigText, err := os.ReadFile(*sig)
		if err != nil {
			fail(err.Error())
		}
		sha, err := signing.FileSHA256(*file)
		if err != nil {
			fail(err.Error())
		}
		if err := signing.Verify(string(pubText), *version, *arch, sha, string(sigText)); err != nil {
			fail(err.Error())
		}
		fmt.Println("signature ok")
	default:
		fail("unknown command " + os.Args[1])
	}
}

func privateKey() ed25519.PrivateKey {
	raw := strings.TrimSpace(os.Getenv("COPILOT_SIGNING_KEY"))
	if raw == "" {
		fail("COPILOT_SIGNING_KEY is not set")
	}
	priv, err := signing.PrivateKeyFromPEM([]byte(raw))
	if err != nil {
		fail(err.Error())
	}
	return priv
}

func need(values ...string) {
	for _, v := range values {
		if v == "" {
			fail("missing argument")
		}
	}
}

func fail(msg string) {
	fmt.Fprintln(os.Stderr, "copilot-sign:", msg)
	os.Exit(1)
}
