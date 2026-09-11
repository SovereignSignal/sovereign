import Foundation

// The installed command uses bundled Python; a source checkout is unnecessary.
let arguments = Array(CommandLine.arguments.dropFirst())
let resources = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Resources")
let task = Process()
task.executableURL = URL(fileURLWithPath: "/bin/bash")
task.arguments = [resources.appendingPathComponent("backend/bin/sov").path] + (arguments.isEmpty ? ["about"] : arguments)
var env = ProcessInfo.processInfo.environment
env["PATH"] = (env["PATH"] ?? "") + ":/usr/bin:/bin:/usr/sbin:/sbin"
env["SOV_PYTHON"] = resources.appendingPathComponent("runtime/bin/python3").path
env["SOV_PYTHON_RUNTIME"] = resources.appendingPathComponent("runtime").path
task.environment = env
do { try task.run(); task.waitUntilExit(); exit(task.terminationStatus) }
catch { fputs("The Sovereign command could not start.\n", stderr); exit(1) }
