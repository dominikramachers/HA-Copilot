package collect

import (
	"context"
	"testing"
)

func TestParsers(t *testing.T) {
	if a, b, c := ParseLoad("0.52 0.40 0.31 1/234 5678\n"); a != 0.52 || b != 0.40 || c != 0.31 {
		t.Fatal(a, b, c)
	}
	if a, _, _ := ParseLoad("kaputt"); a != 0 {
		t.Fatal("unlesbare Auslastung muss 0 sein")
	}
	mounts := ParseMounts("proc /proc proc rw 0 0\n/dev/sda1 / ext4 rw 0 0\ntmpfs /run tmpfs rw 0 0\n/dev/sdb1 /mnt/my\\040data xfs rw 0 0\n/dev/loop0 /snap/core/1 squashfs ro 0 0\n/dev/sda1 / ext4 rw 0 0\n")
	if len(mounts) != 2 || mounts[0].Path != "/" || mounts[1].Path != "/mnt/my data" {
		t.Fatalf("%+v", mounts)
	}
	names := ParseFailedUnits("● foo.service loaded failed failed Foo\n  bar.mount loaded failed failed Bar\n")
	if len(names) != 2 || names[0] != "foo.service" || names[1] != "bar.mount" {
		t.Fatalf("%v", names)
	}
	if n := ParseUpdates("Listing...\nlibc6/stable 2.36 amd64 [upgradable from: 2.35]\ncurl/stable 7 amd64 [upgradable from: 6]\n"); n != 2 {
		t.Fatal(n)
	}
}

func TestCollectFillsTheRequiredFields(t *testing.T) {
	c := &Collector{Version: "9.9.9"}
	hb := c.Collect(context.Background())
	if hb.T != "heartbeat" || hb.Hostname == "" || hb.Arch == "" || hb.AgentVersion != "9.9.9" || hb.CPUs < 1 || hb.FailedUnitNames == nil {
		t.Fatalf("%+v", hb)
	}
}
