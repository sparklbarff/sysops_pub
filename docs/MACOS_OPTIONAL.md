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
