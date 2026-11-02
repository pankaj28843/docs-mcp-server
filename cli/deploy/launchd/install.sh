#!/bin/sh
# Install a persistent user service. Run as the documentation data owner.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
label=org.docs-mcp-server.docsearchd
plist="$HOME/Library/LaunchAgents/$label.plist"
bin_dir="$HOME/.local/bin"
mkdir -p "$bin_dir" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
install -m 755 "$repo/cli/docsearchd" "$bin_dir/.docsearchd.new"
mv "$bin_dir/.docsearchd.new" "$bin_dir/docsearchd"
cat > "$plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict/></plist>
PLIST
/usr/libexec/PlistBuddy -c "Add :Label string $label" "$plist"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments array' "$plist"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:0 string $bin_dir/docsearchd" "$plist"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments:1 string --data-dir' "$plist"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:2 string $repo/mcp-data" "$plist"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments:3 string --deployment-config' "$plist"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:4 string $repo/deployment.json" "$plist"
/usr/libexec/PlistBuddy -c 'Add :ProgramArguments:5 string --listen' "$plist"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:6 string ${DOCSEARCH_LISTEN:-127.0.0.1:42142}" "$plist"
/usr/libexec/PlistBuddy -c 'Add :RunAtLoad bool true' "$plist"
/usr/libexec/PlistBuddy -c 'Add :KeepAlive bool true' "$plist"
/usr/libexec/PlistBuddy -c 'Add :ThrottleInterval integer 5' "$plist"
/usr/libexec/PlistBuddy -c "Add :StandardOutPath string $HOME/Library/Logs/docsearchd.log" "$plist"
/usr/libexec/PlistBuddy -c "Add :StandardErrorPath string $HOME/Library/Logs/docsearchd.error.log" "$plist"
plutil -lint "$plist"
domain="gui/$(id -u)"
if launchctl print "$domain/$label" >/dev/null 2>&1; then
    launchctl bootout "$domain/$label"
fi
launchctl bootstrap "$domain" "$plist"
launchctl print "$domain/$label"
