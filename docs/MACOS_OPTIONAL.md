# Optional macOS module

The private system manages Homebrew packages, system defaults, the Dock, shell configuration,
window management, LaunchAgents, themes, privacy checks, and password-store integration. Those
personal values are not useful as defaults for another person.

The reusable part is the lifecycle:

1. Declare a component and its desired state.
2. Validate configuration syntax before application.
3. Preview exact changes.
4. Apply only the requested component.
5. Read the operating system independently to verify the result.
6. Report drift without silently repairing it.

This repository includes no executable macOS mutation component. A future optional module should
start with one harmless setting, require macOS explicitly, print the current and desired values,
and ship rollback plus verification in the same change.

Good first candidates are a shell snippet copied into an application-owned config directory or a
single reversible application preference. Poor first candidates are password stores, LaunchAgents,
privacy firewalls, system-volume changes, or application binary patching.

## Optional iTerm2 agent status

`examples/macos/iterm_agent_status.py` is a non-mutating adapter for iTerm2's user-variable escape
sequence. It publishes only a sanitized final project-directory label and one of four states:
`Idle`, `Working`, `Waiting`, or `Ended`. It never publishes a full path, prompt, command, transcript,
or task content.

Preview the value without emitting a terminal escape sequence:

```text
python3 examples/macos/iterm_agent_status.py --project ./example --state working --preview
```

In iTerm2, add a Session Status component whose interpolated string reads the `agent_status` user
variable. Agent lifecycle integration is deliberately not installed by this repository. Call the
script from reviewed start, work, wait, and stop hooks only after proving each hook reaches the
intended session.
