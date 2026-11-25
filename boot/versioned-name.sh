#!/bin/sh
# A built image under its release name: the fpvOS version before its
# extension, FILE itself left as a link to it for the commands and scripts
# that use the plain name; earlier versions' copies beside it go.
#   versioned-name.sh FILE VERSION [STEM]
#   images/fpvos-p1-air.fwu 2026.11.beta1  -> images/fpvos-p1-air-2026.11.beta1.fwu
#   images/sdcard.img.xz 2026.11.beta1 fpvos-vrxpro -> images/fpvos-vrxpro-2026.11.beta1.img.xz
# STEM names it otherwise than FILE (default: FILE's name less its extension).
# Prints the new file's path.
set -eu
file=$1 version=$2
dir=$(dirname "$file") name=$(basename "$file")
case "$name" in
	*.img.xz) ext=.img.xz ;;
	*.*) ext=.${name##*.} ;;
	*) ext= ;;
esac
stem=${3:-${name%"$ext"}}
new=$stem-$version$ext
case "$version" in
	''|*/*|*' '*) echo "versioned-name: bad version '$version'" >&2; exit 1 ;;
esac
real=$(readlink -f "$file")
[ -f "$real" ] || { echo "versioned-name: no $file" >&2; exit 1; }
[ "$real" = "$dir/$new" ] || mv -f "$real" "$dir/$new"
# Earlier versions' copies: a version starts with a digit (fpvos-version).
for old in "$dir/$stem"-[0-9]*"$ext"; do
	[ -f "$old" ] && [ ! -L "$old" ] && [ "$old" != "$dir/$new" ] || continue
	rm -f "$old"
done
ln -sfn "$new" "$file"
echo "$dir/$new"
