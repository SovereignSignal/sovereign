import Foundation

// Offline introduction from the installed bundle, independent of shell PATH.
let arguments = Array(CommandLine.arguments.dropFirst())
if !arguments.isEmpty && arguments[0] != "about" {
    fputs("Bundled Sovereign entry point: about [--json].\n", stderr)
    exit(64)
}
let resources = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Resources")
let task = Process()
task.executableURL = resources.appendingPathComponent("runtime/bin/python3")
task.arguments = ["-B", resources.appendingPathComponent("backend/bin/brain-about").path]
    + Array(arguments.dropFirst())
do { try task.run(); task.waitUntilExit(); exit(task.terminationStatus) }
catch { fputs("Sovereign introduction could not start.\n", stderr); exit(1) }
