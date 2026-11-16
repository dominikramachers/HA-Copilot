package tlsutil

import (
	"crypto/x509"
	"testing"
	"time"

	"github.com/dominikramachers/ha-copilot/agent/internal/testpki"
)

func chain(c *testpki.CA, opt testpki.Options) [][]byte {
	return c.ServerChain(opt).Certificate
}

func TestVerifyAcceptsHubSignedByPinnedCA(t *testing.T) {
	ca := testpki.NewCA()
	if err := verifyAgainstPinnedCA(Fingerprint(ca.DER), chain(ca, testpki.Options{}), time.Now()); err != nil {
		t.Fatal(err)
	}
}

func TestVerifyRejectsWrongFingerprint(t *testing.T) {
	ca, other := testpki.NewCA(), testpki.NewCA()
	if err := verifyAgainstPinnedCA(Fingerprint(other.DER), chain(ca, testpki.Options{}), time.Now()); err == nil {
		t.Fatal("ein Hub mit fremder CA darf nicht vertrauenswürdig sein")
	}
}

func TestVerifyRejectsForeignLeafEvenIfPinnedCAIsInTheChain(t *testing.T) {
	ca, attacker := testpki.NewCA(), testpki.NewCA()
	forged := chain(attacker, testpki.Options{})
	forged[1] = ca.DER // der Angreifer hängt die echte CA an, das Blatt ist aber von ihm
	if err := verifyAgainstPinnedCA(Fingerprint(ca.DER), forged, time.Now()); err == nil {
		t.Fatal("ein Zertifikat, das nicht von der angehefteten CA stammt, wurde akzeptiert")
	}
}

func TestVerifyRejectsExpiredAndWrongUsage(t *testing.T) {
	ca := testpki.NewCA()
	fp := Fingerprint(ca.DER)
	expired := chain(ca, testpki.Options{NotAfter: time.Now().Add(-30 * time.Minute)})
	if err := verifyAgainstPinnedCA(fp, expired, time.Now()); err == nil {
		t.Fatal("abgelaufenes Zertifikat akzeptiert")
	}
	key := ca.ServerChain(testpki.Options{}).PrivateKey
	_ = key
	client := ca.Issue(&ca.Key.PublicKey, "x", testpki.Options{Usage: x509.ExtKeyUsageClientAuth})
	if err := verifyAgainstPinnedCA(fp, [][]byte{client, ca.DER}, time.Now()); err == nil {
		t.Fatal("ein Client-Zertifikat darf nicht als Hub durchgehen")
	}
}

func TestVerifyRejectsCAUsedAsServerCertificateAndEmptyChain(t *testing.T) {
	ca := testpki.NewCA()
	fp := Fingerprint(ca.DER)
	if err := verifyAgainstPinnedCA(fp, [][]byte{ca.DER}, time.Now()); err == nil {
		t.Fatal("CA als Serverzertifikat akzeptiert")
	}
	if err := verifyAgainstPinnedCA(fp, nil, time.Now()); err == nil {
		t.Fatal("leere Kette akzeptiert")
	}
}

func TestNormalizeFingerprint(t *testing.T) {
	hex := "ab" + "cd"
	for len(hex) < 64 {
		hex += "0f"
	}
	for _, in := range []string{"sha256:" + hex, hex, " SHA256:" + hex + " "} {
		got, err := NormalizeFingerprint(in)
		if err != nil || got != "sha256:"+hex {
			t.Fatalf("%q -> %q, %v", in, got, err)
		}
	}
	for _, in := range []string{"", "sha256:abc", "sha256:" + hex[:63] + "z", hex + "00"} {
		if _, err := NormalizeFingerprint(in); err == nil {
			t.Fatalf("%q sollte abgelehnt werden", in)
		}
	}
}

func TestKeyAndCSR(t *testing.T) {
	key, err := NewKey()
	if err != nil {
		t.Fatal(err)
	}
	csr, err := CSRPEM(key, "web01")
	if err != nil || len(csr) < 100 {
		t.Fatalf("csr: %v", err)
	}
}
