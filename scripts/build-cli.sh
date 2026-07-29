#!/bin/sh
set -eu

target=${1:?target required}
dist=${2:-dist}

case "$target" in
  darwin-arm64) goos=darwin; goarch=arm64; archive=tar.gz ;;
  darwin-amd64) goos=darwin; goarch=amd64; archive=tar.gz ;;
  linux-arm64) goos=linux; goarch=arm64; archive=tar.gz ;;
  linux-amd64) goos=linux; goarch=amd64; archive=tar.gz ;;
  windows-arm64) goos=windows; goarch=arm64; archive=zip ;;
  windows-amd64) goos=windows; goarch=amd64; archive=zip ;;
  *) echo "unknown target: $target" >&2; exit 2 ;;
esac

mkdir -p "$dist"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

binary=4orm
if [ "$goos" = windows ]; then binary=4orm.exe; fi

CGO_ENABLED=0 GOOS="$goos" GOARCH="$goarch" go build \
  -trimpath -ldflags='-s -w' -o "$work/$binary" ./cmd/4orm

if [ "$archive" = zip ]; then
  (cd "$work" && zip -q "$OLDPWD/$dist/4orm-$target.zip" "$binary")
else
  tar -C "$work" -czf "$dist/4orm-$target.tar.gz" "$binary"
fi
