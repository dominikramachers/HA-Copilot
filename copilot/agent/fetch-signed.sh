#!/bin/sh
# Beim Bauen des Add-ons: die vom Release-Workflow signierten Agenten-Programme holen und prüfen.
#
#   fetch-signed.sh VERSION RELEASE_URL PUBKEY_DATEI PRUEFWERKZEUG ZIELORDNER
#
# Holt je Architektur die Programmdatei und ihre Signatur aus dem GitHub-Release v<VERSION>, prüft beides gegen den öffentlichen
# Schlüssel im Repository (update_key.pub) und legt sie nur dann in den Zielordner, wenn BEIDE Architekturen stimmen. Sonst bleibt
# alles, wie es ist: Die lokal gebauten Programme bleiben unsigniert im Zielordner (Server mit update_key nehmen sie dann nicht an,
# alle anderen schon). Das Skript bricht den Bau nie ab.
version=$1 base=$2 pub=$3 sign=$4 out=$5

if [ ! -s "$pub" ]; then
    echo "agent: no update_key.pub in the repository, the agent files stay unsigned"
    exit 0
fi
case "$version" in
    "" | dev)
        echo "agent: no release version (BUILD_VERSION=$version), the agent files stay unsigned"
        exit 0
        ;;
esac

tmp=$(mktemp -d) || exit 0
for arch in amd64 arm64; do
    f=copilot-agent-linux-$arch
    if curl -fsSL --retry 2 --connect-timeout 10 --max-time 180 -o "$tmp/$f" "$base/v$version/$f" \
        && curl -fsSL --retry 2 --connect-timeout 10 --max-time 60 -o "$tmp/$f.sig" "$base/v$version/$f.sig" \
        && "$sign" verify -pub "$pub" -version "$version" -arch "$arch" -file "$tmp/$f" -sig "$tmp/$f.sig" > /dev/null 2>&1; then
        :
    else
        echo "agent: no valid signed $f for version $version in the release, the agent files stay unsigned"
        rm -rf "$tmp"
        exit 0
    fi
done

for arch in amd64 arm64; do
    f=copilot-agent-linux-$arch
    cp "$tmp/$f" "$out/$f" && chmod 0755 "$out/$f" && cp "$tmp/$f.sig" "$out/$f.sig"
done
cp "$pub" "$out/update_key.pub"
rm -rf "$tmp"
echo "agent: signed agent files for version $version installed"
exit 0
