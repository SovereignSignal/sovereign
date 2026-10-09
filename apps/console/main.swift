// Sovereign console: a thin native shell around `sov status --json`.
//
// Two ways in, one UI. The window is the full console. The menu-bar item pops a
// small Glance panel (the same ui/index.html loaded with #glance) that shows the
// numbers that move and opens the window at the right place. A bridge per web
// view runs `sov`, streams command output, and hands JSON back. The app never
// promotes knowledge automatically; archive access uses the bundled engine.
// The gate goes through `sov gate`, connectors through
// `sov connect`, exactly as the terminal does.
//
// Settings live in UserDefaults on each machine: where the app lives (Dock,
// menu bar, both), open at login, refresh interval, default view.
//
// Build: apps/console/build.sh (swiftc, no Xcode project needed).
import Cocoa
import WebKit
import ServiceManagement

enum Settings {
    // Snapshot QA may persist preferences in its own suite, never the owner's domain.
    static let d: UserDefaults = {
        let env = ProcessInfo.processInfo.environment
        if env["SOV_SNAPSHOT"] != nil, let suite = env["SOV_QA_DEFAULTS_SUITE"], suite.hasPrefix("com.sovereign.qa.") {
            return UserDefaults(suiteName: suite)!
        }
        return .standard
    }()
    static let appearances = ["system", "dark", "light"]
    static var appearance: String {
        get { let v = d.string(forKey: "sov.appearance") ?? "system"; return appearances.contains(v) ? v : "system" }
        set { if appearances.contains(newValue) { d.set(newValue, forKey: "sov.appearance") } }
    }
    static var location: String { get { d.string(forKey: "sov.where") ?? "dock" } set { d.set(newValue, forKey: "sov.where") } }
    static var loginItem: Bool { get { d.bool(forKey: "sov.loginItem") } set { d.set(newValue, forKey: "sov.loginItem") } }
    static var refresh: Int { get { let v = d.integer(forKey: "sov.refresh"); return v > 0 ? v : 60 } set { d.set(newValue, forKey: "sov.refresh") } }
    static var defaultView: String { get { d.string(forKey: "sov.defaultView") ?? "glance" } set { d.set(newValue, forKey: "sov.defaultView") } }
    // Closing the window keeps Sovereign running by default: it is a monitor, and the
    // owner closing a window is not the owner asking the watch to stop. Opt in to quit.
    static var closeQuits: Bool { get { d.bool(forKey: "sov.closeQuits") } set { d.set(newValue, forKey: "sov.closeQuits") } }
    static var lastError: String? = nil
    static var archive: String? { get { d.string(forKey: "sov.archive") } set { d.set(newValue, forKey: "sov.archive") } }

    // A reversible view preference, scoped to the selected archive on this Mac.
    static func archiveKey(_ root: String) -> String {
        URL(fileURLWithPath: root).standardizedFileURL.resolvingSymlinksInPath().path
    }
    static func disassociatedDevices(_ root: String) -> [String] {
        (d.dictionary(forKey: "sov.deviceAssociations") as? [String: [String]])?[archiveKey(root)] ?? []
    }
    static func associateDevice(_ name: String, associated: Bool, root: String) {
        var all = d.dictionary(forKey: "sov.deviceAssociations") as? [String: [String]] ?? [:]
        let key = archiveKey(root)
        var names = Set(all[key] ?? [])
        if associated { names.remove(name) } else { names.insert(name) }
        if names.isEmpty { all.removeValue(forKey: key) } else { all[key] = names.sorted() }
        d.set(all, forKey: "sov.deviceAssociations")
    }

    static func backupExclusions(_ root: String) -> [String] {
        (d.dictionary(forKey: "sov.backupExclusions") as? [String: [String]])?[archiveKey(root)] ?? []
    }
    static func requireBackup(_ id: String, required: Bool, root: String) {
        var all = d.dictionary(forKey: "sov.backupExclusions") as? [String: [String]] ?? [:]
        let key = archiveKey(root)
        var ids = Set(all[key] ?? [])
        if required { ids.remove(id) } else { ids.insert(id) }
        if ids.isEmpty { all.removeValue(forKey: key) } else { all[key] = ids.sorted() }
        d.set(all, forKey: "sov.backupExclusions")
    }

    static func dict(probe: Bool = false) -> [String: Any] {
        // Asking launchd about the login item is synchronous and can block an ad-hoc
        // signed app; do it only when the settings pane is open, never on the boot path.
        var login = loginItem ? "on (as saved)" : "off"
        if probe, #available(macOS 13, *) {
            switch SMAppService.mainApp.status {
            case .enabled: login = "on"
            case .requiresApproval: login = "needs approval in System Settings › Login Items"
            default: login = "off"
            }
        }
        var out: [String: Any] = ["where": location, "loginItem": loginItem, "loginState": login,
                                  "refresh": refresh, "defaultView": defaultView, "closeQuits": closeQuits, "appearance": appearance,
                                  "bundle": Bundle.main.bundlePath]
        if let e = lastError { out["error"] = e }
        return out
    }
}

final class Bridge: NSObject, WKScriptMessageHandler {
    weak var web: WKWebView?
    let sov: String?
    var generation = UUID()
    var gateBusy = false
    var hubBusy = false
    var hubReview: String?
    var archiveBackupBusy = false
    var archiveBackupReview: String?
    var backupBusy = false
    var appUpdateBusy = false
    var appUpdateProcess: Process?
    var discoveryBusy = false
    var producerBusy = false
    var producerReview: String?
    // Status lives across document swaps, scoped to the selected archive and query.
    // All of this state is accessed on the main queue; old requests cannot replace it.
    var statusCache: [String: Any]?
    var statusScope = ""
    var statusRun: UUID?
    var statusWaiter: (generation: UUID, request: Any?)?
    var statusTimer: DispatchWorkItem?
    var statusStarted = Date()
    var statusBudget: Double {
        if App.shared.snapshotting, let value = ProcessInfo.processInfo.environment["SOV_QA_STATUS_BUDGET"],
           let seconds = Double(value), seconds >= 1, seconds <= 45 { return seconds }
        return 45
    }

    init(sov: String?) { self.sov = sov }

    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard let d = m.body as? [String: Any], let cmd = d["cmd"] as? String else { return }
        let generation = self.generation
        switch cmd {
        case "localState":
            deliver("localState", Settings.archive.map { ["root": $0] } ?? [:])
        case "chooseArchive":
            DispatchQueue.main.async { App.shared.chooseArchive(create: (d["create"] as? Bool) == true) }
        case "local":
            guard let action = d["action"] as? String, ["read", "context"].contains(action),
                  let root = Settings.archive else { return }
            var request = d
            request["root"] = root
            local(request) { result in
                var response = result
                response["action"] = action; response["request"] = d["request"]
                self.deliver("local", response, generation: generation)
            }
        case "navigate":
            guard let page = d["page"] as? String, ["home", "review", "operations"].contains(page) else { return }
            DispatchQueue.main.async { App.shared.navigate(page: page, place: d["place"] as? [String: Any]) }
        case "status":
            requestStatus(d, generation: generation)
        case "backupScope":
            setBackupScope(d, generation: generation)
        case "deviceAssociation":
            setDeviceAssociation(d, generation: generation)
        case "archiveBackup":
            archiveBackup(d, generation: generation)
        case "archiveBackupPick":
            guard !archiveBackupBusy, let field = d["field"] as? String,
                  ["folder", "key", "backup", "destination"].contains(field) else { return }
            // Restore reads a key that exists; a Save panel would ask to replace it.
            let existingKey = field == "key" && d["action"] as? String == "restore"
            if (field == "key" && !existingKey) || field == "destination" {
                let panel = NSSavePanel()
                panel.title = field == "key" ? "Recovery key location" : "New restore folder"
                panel.nameFieldStringValue = field == "key" ? "sovereign-recovery.key" : "Restored Sovereign"
                panel.canCreateDirectories = true
                if panel.runModal() == .OK, let url = panel.url { deliver("archiveBackupPicked", ["field": field, "path": url.path]) }
            } else {
                let panel = NSOpenPanel(); panel.canChooseDirectories = field == "folder"
                panel.canChooseFiles = field != "folder"; panel.allowsMultipleSelection = false
                if existingKey { panel.title = "Choose the recovery key" }
                if field == "folder" {
                    panel.title = "Choose a backup folder"
                    panel.canCreateDirectories = true
                    panel.directoryURL = URL(fileURLWithPath: d["location"] as? String == "volumes" ? "/Volumes" : NSHomeDirectory())
                }
                if panel.runModal() == .OK, let url = panel.url { deliver("archiveBackupPicked", ["field": field, "path": url.path]) }
            }
        case "hubDefaults":
            let home = App.shared.snapshotting ? ProcessInfo.processInfo.environment["SOV_QA_HUB_HOME"] ?? NSHomeDirectory() : NSHomeDirectory()
            deliver("hubDefaults", ["home": home])
        case "hubPick":
            guard !hubBusy, let field = d["field"] as? String, ["config", "key-file", "capsule", "folder"].contains(field) else { return }
            let panel = NSOpenPanel()
            panel.canChooseDirectories = field == "folder"
            panel.canChooseFiles = !panel.canChooseDirectories
            panel.allowsMultipleSelection = false
            if panel.runModal() == .OK, let url = panel.url { deliver("hubPicked", ["field": field, "path": url.path]) }
        case "retryBackup":
            retryBackup(d, generation: generation)
        case "appUpdate":
            appUpdate(d, generation: generation)
        case "hubOperation":
            hubOperation(d, generation: generation)
        case "discover":
            discoverTools(d, generation: generation)
        case "producer":
            manageProducer(d, generation: generation)
        case "connect":
            guard let sov = sov else { refuse(d, "connect", "sov is not installed on this machine.", generation: generation); return }
            guard let h = d["harness"] as? String else { refuse(d, "connect", "No tool was named.", generation: generation); return }
            var args = [sov, "connect", h]
            for (flag, key) in [("--host", "host"), ("--vault", "vault"), ("--core", "core"), ("--hub", "hub")] {
                if let v = d[key] as? String, !v.isEmpty { args += [flag, v] }
            }
            if (d["apply"] as? Bool) == true { args.append("--apply") }
            // a secret rides in the child's environment only: never on argv, never in the log
            var secretEnv: [String: String] = [:]
            if let v = d["secret"] as? String, let k = d["secretEnv"] as? String, !v.isEmpty,
               k.range(of: "^[A-Z_][A-Z0-9_]*$", options: .regularExpression) != nil { secretEnv[k] = v }
            stream(args, id: "connect", request: d["request"], generation: generation, env: secretEnv)
        case "hostadd":
            // the hub does the work (sov routes there); the drawer streams it
            guard let sov = sov else { refuse(d, "hostadd", "sov is not installed on this machine.", generation: generation); return }
            guard let name = d["name"] as? String,
                  name.range(of: "^[a-z0-9][a-z0-9-]{1,40}$", options: .regularExpression) != nil else {
                refuse(d, "hostadd", "\((d["name"] as? String) ?? "This device") cannot join through host add: its name must be lowercase letters, digits and hyphens.", generation: generation); return
            }
            var args = [sov, "host", "add", name]
            for (flag, key) in [("--user", "user"), ("--addr", "addr"), ("--identity", "identity"), ("--workstreams", "workstreams")] {
                if let v = d[key] as? String, !v.isEmpty { args += [flag, v] }
            }
            if (d["apply"] as? Bool) == true { args.append("--apply") }
            stream(args, id: "hostadd", request: d["request"], generation: generation)
        case "vmstart":
            guard let name = d["name"] as? String, !name.isEmpty else { deliver("vmstart", ["name": "", "exit": 64, "out": "No VM was named."], generation: generation); return }
            run(["/usr/local/bin/prlctl", "start", name]) { out, err, code in
                self.deliver("vmstart", ["name": name, "exit": code, "out": out + err], generation: generation)
            }
        case "kickstart":
            guard let label = d["label"] as? String else {
                deliver("kickstart", ["label": "", "exit": 64, "out": "No job was named.", "request": d["request"] ?? NSNull()], generation: generation); return
            }
            // A lane row asks for ITS lane, not the whole job. The shared runner takes --only, so
            // run that directly: kickstarting the job would kill the tick in flight (-k) and then
            // run every lane, which is not what the row said it would do. The runner sits beside
            // the sov binary. Anything without a lane is still a whole-job kickstart.
            let lane = (d["lane"] as? String).flatMap { l in
                l.range(of: "^[a-z0-9][a-z0-9-]{0,60}$", options: .regularExpression) != nil ? l : nil
            }
            let runner = sov.map { URL(fileURLWithPath: $0).deletingLastPathComponent()
                                       .appendingPathComponent("sov-connectors-run").path }
            // "done": the reply comes after the work, not when it starts (a launchctl kickstart)
            let request = d["request"] ?? NSNull()
            if let lane = lane, let runner = runner, FileManager.default.isExecutableFile(atPath: runner) {
                // The runner bounds each lane itself; this bounds the reply the drawer waits on.
                run([runner, "--only", lane], timeLimit: 900) { out, err, code in
                    self.deliver("kickstart", ["label": lane, "exit": code, "out": out + err, "request": request, "done": true], generation: generation)
                }
            } else {
                run(["/bin/launchctl", "kickstart", "-k", "gui/\(getuid())/\(label)"]) { out, err, code in
                    self.deliver("kickstart", ["label": label, "exit": code, "out": out + err, "request": request], generation: generation)
                }
            }
        case "clearlog":
            if let p = d["path"] as? String, p.hasSuffix(".log"), p.hasPrefix(NSHomeDirectory()) {
                try? "".write(toFile: p, atomically: true, encoding: .utf8)
                deliver("kickstart", ["label": "cleared " + (p as NSString).lastPathComponent, "exit": 0, "out": "", "request": d["request"] ?? NSNull(), "done": true], generation: generation)
            } else {
                deliver("kickstart", ["label": "clear log", "exit": 1, "out": "Only a .log file in your home folder can be cleared here.", "request": d["request"] ?? NSNull(), "done": true], generation: generation)
            }
        case "reveal":
            if let p = d["path"] as? String { NSWorkspace.shared.selectFile(p, inFileViewerRootedAtPath: "") }
        case "open":
            if let p = d["path"] as? String { NSWorkspace.shared.open(URL(fileURLWithPath: p)) }
        case "clientError":
            // The page cannot print; WebKit sanitises its own errors to "Script error."
            // This is how a real message reaches the app log and a QA run.
            log("client error in \((d["where"] as? String) ?? "?"): \((d["msg"] as? String) ?? "")")
        case "openurl":
            if let u = d["url"] as? String, let url = URL(string: u),
               ["https", "http", "obsidian"].contains(url.scheme?.lowercased() ?? ""), url.host != nil {
                NSWorkspace.shared.open(url)
            }
        case "gateCheck", "gate":
            guard let slug = d["slug"] as? String,
                  slug.range(of: "^[a-z0-9][a-z0-9-]{0,120}$", options: .regularExpression) != nil,
                  let request = d["request"] as? String, request.count < 100 else { return }
            let mode = cmd == "gateCheck" ? "check" : (d["verb"] as? String ?? "")
            guard ["check", "approve", "reject", "resolve"].contains(mode) else { return }
            let kind = cmd == "gateCheck" ? "gateCheck" : "gateResult"
            func reply(_ payload: [String: Any]) {
                var result = payload; result["slug"] = slug; result["request"] = request
                self.deliver(kind, result, generation: generation)
            }
            if gateBusy { reply(["state": "busy"]); return }
            guard let resource = Bundle.main.url(forResource: "gate_check", withExtension: "py"),
                  let source = try? String(contentsOf: resource, encoding: .utf8) else { reply(["state": "unavailable"]); return }
            let fingerprint = d["fingerprint"] as? String ?? ""
            if mode != "check" && fingerprint.range(of: "^[a-f0-9]{64}$", options: .regularExpression) == nil { reply(["state": "changed"]); return }
            let via = d["via"] as? String ?? "local"
            let args: [String]
            if via.hasPrefix("ssh ") {
                let alias = String(via.dropFirst(4))
                guard alias.range(of: "^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$", options: .regularExpression) != nil else { reply(["state": "unavailable"]); return }
                func quote(_ value: String) -> String { "'" + value.replacingOccurrences(of: "'", with: "'\"'\"'") + "'" }
                let remote = ["/usr/bin/python3", "-c", source, mode, slug, fingerprint].map(quote).joined(separator: " ")
                args = ["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3", alias, remote]
            } else {
                guard via == "local", let runtime = Bundle.main.resourceURL?.appendingPathComponent("runtime/bin/python3") else { reply(["state": "unavailable"]); return }
                args = [runtime.path, "-I", "-B", "-c", source, mode, slug, fingerprint]
            }
            if mode != "check" { gateBusy = true }
            var gateEnvironment: [String: String] = [:]
            if App.shared.snapshotting, via == "local", let qaHome = ProcessInfo.processInfo.environment["SOV_QA_GATE_HOME"] { gateEnvironment["HOME"] = qaHome }
            run(args, environment: gateEnvironment) { out, err, _ in
                var result = (out.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]) ?? ["state": mode == "check" ? "unavailable" : "uncertain"]
                let detail = (result["detail"] as? String ?? "") + (err.isEmpty ? "" : "\n" + err)
                if !detail.isEmpty { result["detail"] = self.statusDetail(detail) }
                DispatchQueue.main.async {
                    if mode != "check" { self.gateBusy = false }
                    reply(result)
                }
            }
        case "qaQuit":
            // Exercises the real native quit dispatch, only in disposable snapshot QA.
            guard App.shared.snapshotting else { return }
            NSApp.terminate(nil)
        case "copyText":
            guard let text = d["text"] as? String, text.utf8.count <= 16000 else { return }
            NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string)
        case "settings":
            deliver("settings", Settings.dict(probe: (d["probe"] as? Bool) == true))
        case "appearance":
            guard let value = d["value"] as? String, Settings.appearances.contains(value) else { return }
            App.shared.setAppearance(value)
        case "qaAppearance":
            // Simulate a system appearance notification without changing macOS preferences.
            guard App.shared.snapshotting else { return }
            if let value = d["systemTheme"] as? String, ["dark", "light"].contains(value), Settings.appearance == "system" {
                NSApp.appearance = NSAppearance(named: value == "dark" ? .darkAqua : .aqua)
            }
            if (d["openGlance"] as? Bool) == true { App.shared.prepareGlance() }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                let app = App.shared!
                app.glanceWeb?.evaluateJavaScript("document.documentElement.dataset.theme") { value, _ in
                    log("appearance glance: \(value ?? "unavailable")")
                }
                log("appearance native: \(app.theme) saved=\(Settings.appearance) inherited=\(NSApp.appearance == nil)")
            }
        case "setSettings":
            if let w = d["where"] as? String, ["dock", "menubar", "both"].contains(w) { Settings.location = w }
            var loginChanged = false
            if let l = d["loginItem"] as? Bool, l != Settings.loginItem { Settings.loginItem = l; loginChanged = true }
            if let r = d["refresh"] as? Int, r >= 15, r <= 3600 { Settings.refresh = r }
            if let v = d["defaultView"] as? String, ["glance", "archive", "hosts", "lanes", "tools", "jobs", "backups"].contains(v) { Settings.defaultView = v }
            if let q = d["closeQuits"] as? Bool { Settings.closeQuits = q }
            DispatchQueue.main.async { App.shared.applySettings(loginChanged: loginChanged); App.shared.broadcastSettings() }
        case "showConsole":
            DispatchQueue.main.async { App.shared.showConsole(place: d["place"] as? [String: Any]) }
        case "closeGlance":
            DispatchQueue.main.async { App.shared.popover?.performClose(nil) }
        case "glanceSize":
            if let h = d["h"] as? Double { DispatchQueue.main.async { (NSApp.delegate as? App)?.setGlanceHeight(h) } }
        case "verdict":
            if let st = d["state"] as? String { DispatchQueue.main.async { (NSApp.delegate as? App)?.setVerdictState(st) } }
            if let dir = ProcessInfo.processInfo.environment["SOV_STATUS_SNAPSHOT"], !dir.isEmpty {
                DispatchQueue.main.async { (NSApp.delegate as? App)?.snapshotStatusItem(dir); NSApp.terminate(nil) }
            }
        case "quit":
            DispatchQueue.main.async { NSApp.terminate(nil) }
        default: break
        }
    }

    private func env() -> [String: String] {
        var e = ProcessInfo.processInfo.environment
        let home = NSHomeDirectory()
        e["HOME"] = home
        e["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:\(home)/brain-bin"
        return e
    }

    // This path is independent of shell profiles, Homebrew, Python, Git and fleet pointers.
    func local(_ request: [String: Any], done: @escaping ([String: Any]) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            guard let resources = Bundle.main.resourceURL,
                  let input = try? JSONSerialization.data(withJSONObject: request) else { return }
            let p = Process(), stdin = Pipe(), output = Pipe()
            p.executableURL = resources.appendingPathComponent("runtime/bin/python3")
            p.arguments = ["-I", "-B", resources.appendingPathComponent("backend/bin/sov-local").path]
            p.standardInput = stdin; p.standardOutput = output; p.standardError = output
            p.environment = ["HOME": NSHomeDirectory(), "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"]
            do { try p.run() } catch {
                done(["error": "The bundled archive engine could not start. Download a complete copy of the app."]); return
            }
            let timeout = DispatchWorkItem { if p.isRunning { p.terminate() } }
            DispatchQueue.global().asyncAfter(deadline: .now() + 30, execute: timeout)
            do { try stdin.fileHandleForWriting.write(contentsOf: input) } catch { }
            try? stdin.fileHandleForWriting.close()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            p.waitUntilExit(); timeout.cancel()
            guard let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                done(["error": "The archive engine did not finish. Your existing files have been preserved."]); return
            }
            done(result)
        }
    }

    // Reuse the archive's credential redactor before truncation, so a clipped key
    // cannot evade its shape checks. Failure never falls back to raw diagnostics.
    private func requestStatus(_ request: [String: Any], generation: UUID) {
        let scope = "\(Settings.archive ?? "")|\((request["hub"] as? Bool) != false)"
        if scope != statusScope {
            statusCache = nil; statusRun = nil; statusTimer?.cancel(); statusScope = scope
        }
        statusWaiter = (generation, request["request"])
        guard let sov = sov else {
            deliver("status", ["machine": ["connected": false], "available": false,
                               "request": request["request"] ?? NSNull()], generation: generation)
            return
        }
        // A new page joins the existing read. It does not start another probe.
        sendStatus(pending: true)
        guard statusRun == nil else { return }
        let runID = UUID(); statusRun = runID; statusStarted = Date()
        let deadline = DispatchWorkItem { [weak self] in
            guard let self = self, self.statusRun == runID else { return }
            self.statusRun = nil
            self.sendStatus(pending: false, error: "The connected-system status probe did not finish within \(Int(self.statusBudget)) seconds. Check the connection in Sources, then refresh to confirm a new observation.")
        }
        statusTimer = deadline
        DispatchQueue.main.asyncAfter(deadline: .now() + statusBudget, execute: deadline)
        var args = [sov, "status", "--json"]
        if (request["hub"] as? Bool) == false { args.append("--no-hub") }
        run(args, timeLimit: statusBudget) { out, err, code in
            let obj = out.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            let valid = code == 0 && obj?["error"] == nil && obj?["machine"] is [String: Any]
            let detail = valid ? "" : self.statusDetail(err)
            DispatchQueue.main.async {
                guard self.statusRun == runID else { return }
                self.statusTimer?.cancel(); self.statusRun = nil
                if valid, var value = obj {
                    value["_status"] = ["observed_at": value["generated_at"] ?? ISO8601DateFormatter().string(from: self.statusStarted),
                                        "duration_s": Date().timeIntervalSince(self.statusStarted)]
                    self.statusCache = value
                    self.sendStatus(pending: false)
                } else {
                    self.sendStatus(pending: false, error: "System status could not be read (exit \(code)). Check the connection in Sources and refresh to confirm a new observation.", detail: detail)
                }
            }
        }
    }

    private func sendStatus(pending: Bool, error: String? = nil, detail: String = "") {
        guard let waiter = statusWaiter else { return }
        var value = statusCache ?? [:]
        // archiveKey decides identity here; the pages compare spellings. A connected vault that is
        // the open archive written another way (case, Unicode form, a link) reaches them as the open one.
        if let root = Settings.archive, var machine = value["machine"] as? [String: Any], let vault = machine["vault"] as? String,
           Settings.archiveKey(vault) == Settings.archiveKey(root) { machine["vault"] = root; value["machine"] = machine }
        var state = value["_status"] as? [String: Any] ?? [:]
        state["pending"] = pending; state["stale"] = pending || error != nil
        state["budget_s"] = statusBudget
        if let error = error { state["error"] = error; state["detail"] = detail }
        value["_status"] = state; value["request"] = waiter.request ?? NSNull()
        value["device_associations"] = deviceAssociationState()
        value["backup_scope"] = backupScopeState()
        if statusCache == nil, let error = error { value["error"] = error }
        deliver("status", value, generation: waiter.generation)
    }

    private func retryBackup(_ request: [String: Any], generation: UUID) {
        func fail(_ message: String) { deliver("backupResult", ["error": message], generation: generation) }
        guard !backupBusy, let resources = Bundle.main.resourceURL,
              let root = Settings.archive, let requested = request["root"] as? String,
              Settings.archiveKey(root) == Settings.archiveKey(requested) else {
            fail("Open the configured archive and wait for any backup request to finish."); return
        }
        let qa = App.shared.snapshotting ? ProcessInfo.processInfo.environment["SOV_QA_BACKUP_COMMAND"] : nil
        guard !App.shared.snapshotting || qa != nil else { fail("Live backup actions are disabled during QA."); return }
        let args = qa.map { [$0, "--root", root] } ?? [resources.appendingPathComponent("runtime/bin/python3").path, "-I", "-B", resources.appendingPathComponent("backend/bin/sov-job-action").path, "--root", root]
        backupBusy = true
        run(args, timeLimit: 15) { out, _, code in
            DispatchQueue.main.async {
                guard self.generation == generation, Settings.archive == root else { self.backupBusy = false; return }
                let plan = (out.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any] ?? [:]
                guard code == 0, plan["state"] as? String == "preview", let token = plan["token"] as? String else {
                    self.backupBusy = false; fail(plan["error"] as? String ?? "The backup could not be previewed. Refresh the hub before retrying."); return
                }
                let alert = NSAlert(); alert.messageText = "Run archive backup now?"
                alert.informativeText = [plan["summary"] as? String, plan["effects"] as? String, plan["hub"] as? String, plan["vault"] as? String].compactMap { $0 }.joined(separator: "\n\n")
                alert.addButton(withTitle: "Run backup now"); alert.addButton(withTitle: "Cancel")
                let confirmed: Bool
                if App.shared.snapshotting { confirmed = ProcessInfo.processInfo.environment["SOV_QA_BACKUP_CONFIRM"] == "1" }
                else { confirmed = alert.runModal() == .alertFirstButtonReturn }
                guard confirmed else { self.backupBusy = false; self.deliver("backupResult", ["state": "cancelled"], generation: generation); return }
                guard self.generation == generation, Settings.archive == root else { self.backupBusy = false; return }
                self.run(args + ["--apply", "--token", token], timeLimit: 15) { out, _, code in
                    DispatchQueue.main.async {
                        self.backupBusy = false
                        var result = (out.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any] ?? ["error": "No result returned. Refresh before retrying; the request may have reached the hub."]
                        if code != 0 && result["error"] == nil { result["error"] = "The backup request failed. Refresh before retrying." }
                        self.deliver("backupResult", result, generation: generation)
                    }
                }
            }
        }
    }

    /// Rebuild this machine's source into the installed app.
    ///
    /// The apply step is launched DETACHED on purpose. It replaces this very bundle, so
    /// it has to outlive the process that starts it; run through the normal helper it
    /// would be a child with a pipe and a timeout, and would die with its parent halfway
    /// through a swap. Its output goes to a file for the same reason: a broken pipe when
    /// this app exits must not take the updater with it.
    private func appUpdate(_ request: [String: Any], generation: UUID) {
        func fail(_ message: String) { deliver("appUpdateResult", ["error": message], generation: generation) }
        guard !appUpdateBusy, let resources = Bundle.main.resourceURL else {
            fail("An update is already being prepared."); return
        }
        let qa = App.shared.snapshotting ? ProcessInfo.processInfo.environment["SOV_QA_UPDATE_COMMAND"] : nil
        guard !App.shared.snapshotting || qa != nil else { fail("Updates are disabled during QA."); return }
        // The app cannot build from its own bundle: backend/ ships no apps/console.
        guard let template = request["template"] as? String, !template.isEmpty else {
            fail("This machine's source location is not known, so there is nothing to build from."); return
        }
        let py = resources.appendingPathComponent("runtime/bin/python3").path
        let script = resources.appendingPathComponent("backend/bin/sov-app-update").path
        guard FileManager.default.isReadableFile(atPath: script) else {
            fail("This build of Sovereign predates in-app updating. Install once from the source checkout and the button works from then on."); return
        }
        let base = qa.map { [$0, "--template", template] } ?? [py, "-I", "-B", script, "--template", template]
        appUpdateBusy = true
        run(base + ["--preview"], timeLimit: 60) { out, _, code in
            DispatchQueue.main.async {
                guard self.generation == generation else { self.appUpdateBusy = false; return }
                let plan = (out.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any] ?? [:]
                guard code == 0, plan["state"] as? String == "preview", let token = plan["token"] as? String else {
                    self.appUpdateBusy = false
                    fail(plan["error"] as? String ?? "The update could not be prepared. Refresh and try again."); return
                }
                if plan["current"] as? Bool == true {
                    self.appUpdateBusy = false
                    self.deliver("appUpdateResult", ["state": "current", "verification": plan["summary"] as? String ?? "Sovereign is already up to date."], generation: generation)
                    return
                }
                let alert = NSAlert(); alert.messageText = "Update Sovereign now?"
                alert.informativeText = [plan["summary"] as? String, plan["effects"] as? String].compactMap { $0 }.joined(separator: "\n\n")
                alert.addButton(withTitle: "Update now"); alert.addButton(withTitle: "Cancel")
                let confirmed = App.shared.snapshotting
                    ? ProcessInfo.processInfo.environment["SOV_QA_UPDATE_CONFIRM"] == "1"
                    : alert.runModal() == .alertFirstButtonReturn
                guard confirmed else {
                    self.appUpdateBusy = false
                    self.deliver("appUpdateResult", ["state": "cancelled"], generation: generation); return
                }
                let log = FileManager.default.temporaryDirectory.appendingPathComponent("sovereign-app-update-\(UUID().uuidString).log")
                let started = self.launchDetached(base + ["--apply", "--token", token], logTo: log) { result in
                    self.appUpdateBusy = false
                    self.appUpdateProcess = nil
                    // Report to the current document even if navigation changed during the build.
                    self.deliver("appUpdateResult", result, generation: self.generation)
                }
                if started {
                    self.deliver("appUpdateResult", ["state": "started",
                        "verification": "Building. Sovereign will close and reopen when the new build is ready."], generation: generation)
                } else {
                    self.appUpdateBusy = false
                    fail("The update could not be started. Nothing was changed.")
                }
            }
        }
    }

    /// File output lets the updater survive this app exiting. Observe termination while
    /// the app remains open so a failed build cannot leave a permanent Building banner.
    @discardableResult
    func launchDetached(_ args: [String], logTo log: URL, done: @escaping ([String: Any]) -> Void) -> Bool {
        guard FileManager.default.createFile(atPath: log.path, contents: nil),
              let handle = try? FileHandle(forWritingTo: log) else { return false }
        defer { try? handle.close() }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: args[0])
        p.arguments = Array(args.dropFirst())
        p.environment = env()
        p.standardOutput = handle
        p.standardError = handle
        p.terminationHandler = { process in
            let output = (try? String(contentsOf: log, encoding: .utf8)) ?? ""
            var result = output.split(separator: "\n").reversed().compactMap { line in
                String(line).data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            }.first ?? [:]
            if result["error"] == nil && (process.terminationStatus != 0 || result["state"] as? String != "installed") {
                let detail = String(output.suffix(1200)).trimmingCharacters(in: .whitespacesAndNewlines)
                result = ["error": "The updater stopped (exit \(process.terminationStatus)). \(detail.isEmpty ? "No result was returned." : detail) Log: \(log.path)"]
            }
            let completed = result
            DispatchQueue.main.async { done(completed) }
        }
        do { try p.run() } catch { return false }
        appUpdateProcess = p
        return true
    }

    private func archiveBackup(_ request: [String: Any], generation: UUID) {
        func fail(_ message: String, busy: Bool = false) { deliver("archiveBackupResult", ["error": message, "busy": busy, "request": request["request"] ?? ""], generation: generation) }
        // A page that navigated away from a read and came back can ask while it still runs.
        guard !archiveBackupBusy else { fail("The archive host is still answering an earlier request. Refresh in a moment.", busy: true); return }
        guard let resources = Bundle.main.resourceURL,
              let root = Settings.archive, let requested = request["root"] as? String,
              Settings.archiveKey(root) == Settings.archiveKey(requested),
              let action = request["action"] as? String,
              ["status", "browse", "configure", "reconnect", "backup", "verify", "restore"].contains(action) else {
            fail("Select an archive before managing its backups."); return
        }
        var payload = request
        payload.removeValue(forKey: "cmd"); payload.removeValue(forKey: "request")
        payload["protocol"] = 1; payload["root"] = root
        var review = payload; review.removeValue(forKey: "apply"); review.removeValue(forKey: "token")
        let reviewKey = generation.uuidString + ((try? JSONSerialization.data(withJSONObject: review, options: [.sortedKeys])).flatMap { String(data: $0, encoding: .utf8) } ?? "")
        let apply = payload["apply"] as? Bool == true
        guard !apply || archiveBackupReview == reviewKey else { fail("Preview this exact backup operation before applying it."); return }
        guard let data = try? JSONSerialization.data(withJSONObject: payload), data.count <= 32768,
              let json = String(data: data, encoding: .utf8) else { fail("The backup request is invalid."); return }
        archiveBackupBusy = true
        if !["status", "browse"].contains(action) { archiveBackupReview = nil }
        let home = App.shared.snapshotting ? ProcessInfo.processInfo.environment["SOV_QA_HUB_HOME"] ?? NSHomeDirectory() : NSHomeDirectory()
        var environment = ["HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8",
                           "SOV_PYTHON_RUNTIME": resources.appendingPathComponent("runtime").path]
        if App.shared.snapshotting, let ssh = ProcessInfo.processInfo.environment["SOV_QA_ARCHIVE_BACKUP_SSH"] { environment["SOV_BACKUP_SSH"] = ssh }
        let args = [resources.appendingPathComponent("runtime/bin/python3").path, "-I", "-B",
                    resources.appendingPathComponent("backend/bin/sov-backup").path, "--request", json]
        run(args, environment: environment, timeLimit: apply ? 7400 : 120, isolated: true) { out, _, code in
            DispatchQueue.main.async {
                self.archiveBackupBusy = false
                var result = (out.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any]
                    ?? ["error": "The archive host did not return a result. Refresh to inspect its last attempt before retrying."]
                result["request"] = request["request"] ?? ""; result["action"] = action; result["exit"] = code
                if code == 0 && result["error"] == nil && !apply && !["status", "browse"].contains(action) && self.generation == generation {
                    self.archiveBackupReview = reviewKey
                }
                self.deliver("archiveBackupResult", result, generation: generation)
            }
        }
    }

    private func hubOperation(_ request: [String: Any], generation: UUID) {
        func fail(_ message: String) { deliver("hubResult", ["error": message, "request": request["request"] ?? ""], generation: generation) }
        guard !hubBusy else { fail("An earlier Hub operation is still running. Try again when it finishes."); return }
        guard let resources = Bundle.main.resourceURL,
              let command = request["command"] as? String,
              ["install", "key", "recovery", "snapshot", "restore", "status", "doctor", "activate", "run"].contains(command),
              let root = Settings.archive, let requestedRoot = request["root"] as? String,
              Settings.archiveKey(root) == Settings.archiveKey(requestedRoot) else { fail("Open an archive before managing its Hub."); return }
        var reviewed = request; reviewed.removeValue(forKey: "apply"); reviewed.removeValue(forKey: "request")
        let key = generation.uuidString + ((try? JSONSerialization.data(withJSONObject: reviewed, options: [.sortedKeys])).flatMap { String(data: $0, encoding: .utf8) } ?? "")
        let apply = request["apply"] as? Bool == true
        guard !apply || hubReview == key else { fail("Preview this exact Hub operation before applying it."); return }
        let qaHome = App.shared.snapshotting ? ProcessInfo.processInfo.environment["SOV_QA_HUB_HOME"] : nil
        let home = qaHome ?? NSHomeDirectory()
        if command == "install", (try? String(contentsOfFile: home + "/.brain-hub", encoding: .utf8)).map({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) == true {
            fail("This Mac is configured as a Client. Set up a new Hub on its own Mac; migrate existing roles through a reviewed cutover."); return
        }
        if !["install", "key", "restore"].contains(command) {
            guard let path = request["config"] as? String,
                  let raw = try? Data(contentsOf: URL(fileURLWithPath: path)), raw.count <= 1048576,
                  let config = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
                  let archive = config["archive"] as? String,
                  Settings.archiveKey(archive) == Settings.archiveKey(root) else { fail("Choose the Hub configuration for the open archive."); return }
        }
        let fields: [String: [String]] = ["install": ["destination", "model", "endpoint"], "key": ["output"], "recovery": ["config", "folder", "key-file"], "snapshot": ["config", "output", "key-file"], "restore": ["capsule", "destination", "key-file"], "status": ["config"], "doctor": ["config"], "activate": ["config"], "run": ["config"]]
        var args = [resources.appendingPathComponent("runtime/bin/python3").path, "-I", "-B", resources.appendingPathComponent("backend/bin/sov-managed-hub").path, command]
        if command == "install" { args += ["--archive", root] }
        if command == "run" {
            guard let job = request["job"] as? String, ["nightly", "audit"].contains(job) else { fail("Choose curation or audit."); return }
            args.append(job)
        }
        for field in fields[command] ?? [] {
            guard let value = request[field] as? String, !value.isEmpty, value.count <= 4096,
                  !value.contains("\n"), !value.contains("\r") else { fail("Complete the " + field + " field first."); return }
            args += ["--" + field, value]
        }
        if command == "activate" {
            guard request["singleHub"] as? Bool == true else { fail("Confirm this will be the only active Hub before enabling schedules."); return }
            args.append("--confirm-single-hub")
        }
        if apply { args.append("--apply") }
        hubReview = nil; hubBusy = true
        var env = ["SOV_PYTHON_RUNTIME": resources.appendingPathComponent("runtime").path]
        if let home = qaHome { env["HOME"] = home }
        run(args, environment: env, timeLimit: 1900) { out, _, code in
            DispatchQueue.main.async {
                self.hubBusy = false
                var result = (out.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any] ?? ["error": "Hub operation did not return a result. Inspect its receipts before retrying."]
                // A job run reports its own exit; the wrapper only says whether it was zero.
                if result["exit"] == nil { result["exit"] = code }
                result["command"] = command; result["request"] = request["request"] ?? ""
                if code == 0 && !apply && self.generation == generation && !["status", "doctor"].contains(command) { self.hubReview = key }
                self.deliver("hubResult", result, generation: generation)
            }
        }
    }

    private func discoverTools(_ request: [String: Any], generation: UUID) {
        guard !discoveryBusy, let resources = Bundle.main.resourceURL else { return }
        discoveryBusy = true
        var args = [resources.appendingPathComponent("runtime/bin/python3").path, "-I", "-B",
                    resources.appendingPathComponent("backend/bin/sov-discover").path]
        if App.shared.snapshotting, let home = ProcessInfo.processInfo.environment["SOV_QA_DISCOVERY_HOME"] {
            args += ["--home", home, "--applications", home + "/Applications", "--path", home + "/bin"]
        }
        run(args, timeLimit: 10) { out, _, code in
            DispatchQueue.main.async {
            self.discoveryBusy = false
            var result = (out.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any]
                ?? ["error": "Discovery could not finish. Try Scan again."]
            if code != 0 && result["error"] == nil { result["error"] = "Discovery could not finish. Try Scan again." }
            result["request"] = request["request"]
            self.deliver("discovery", result, generation: generation)
            }
        }
    }

    private func manageProducer(_ request: [String: Any], generation: UUID) {
        func fail(_ message: String) {
            deliver("log", ["id": "producer", "request": request["request"] ?? NSNull(), "line": message, "state": "end", "exit": 65], generation: generation)
        }
        guard !producerBusy else { fail("A producer change is already running."); return }
        guard let sov = sov, let root = Settings.archive,
              let requestedRoot = request["root"] as? String,
              Settings.archiveKey(root) == Settings.archiveKey(requestedRoot),
              let machine = statusCache?["machine"] as? [String: Any],
              let vault = machine["vault"] as? String,
              Settings.archiveKey(root) == Settings.archiveKey(vault),
              let h = request["harness"] as? String,
              h.range(of: "^[a-z][a-z0-9-]*$", options: .regularExpression) != nil,
              let action = request["action"] as? String, ["add", "remove"].contains(action) else {
            fail("Refresh the configured archive before changing a producer."); return
        }
        let template = URL(fileURLWithPath: sov).resolvingSymlinksInPath().deletingLastPathComponent().deletingLastPathComponent()
        let metadata = template.appendingPathComponent("connectors/harness/\(h)/harness.json")
        guard let data = try? Data(contentsOf: metadata),
              let meta = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            fail("This producer is not supported by the installed connector service."); return
        }
        let env = ProcessInfo.processInfo.environment
        let qa = App.shared.snapshotting ? env["SOV_QA_PRODUCER_COMMAND"] : nil
        let pointer = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".brain-root")
        let configuredPointer = (try? String(contentsOf: pointer, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
        let legacyRoot = env["BRAIN_ROOT"].flatMap { $0.isEmpty ? nil : $0 } ?? env["SOVS_VAULT"].flatMap { $0.isEmpty ? nil : $0 }
        let configuredRoot = legacyRoot ?? configuredPointer.flatMap { $0.isEmpty ? nil : $0 } ?? env["SOVEREIGN_ROOT"].flatMap { $0.isEmpty ? nil : $0 } ?? env["SOVEREIGN_VAULT"].flatMap { $0.isEmpty ? nil : $0 }
        guard qa != nil || configuredRoot.map({ Settings.archiveKey($0) }) == Settings.archiveKey(root) else {
            fail("The connector service uses a different archive. Refresh before making changes."); return
        }
        var secret: [String: String] = [:]
        if action == "add", let value = request["secret"] as? String, !value.isEmpty,
           let definition = meta["secret"] as? [String: Any], let key = definition["env"] as? String,
           key.range(of: "^[A-Z_][A-Z0-9_]*$", options: .regularExpression) != nil { secret[key] = value }
        let key = [generation.uuidString, Settings.archiveKey(root), h, action, secret.values.first ?? ""].joined(separator: "\n")
        let apply = request["apply"] as? Bool == true
        guard !apply || producerReview == key else { fail("Review this producer change before applying it."); return }
        producerReview = nil
        producerBusy = true
        var args = [qa ?? sov, action == "add" ? "connect" : "disconnect", h]
        if !(meta["detect"] as? [String] ?? []).isEmpty { args += ["--vault", root] }
        if apply { args.append("--apply") }
        stream(args, id: "producer", request: request["request"], generation: generation, env: secret) { code in
            self.producerBusy = false
            if !apply && code == 0 && self.generation == generation { self.producerReview = key }
        }
    }

    private func backupScopeState() -> [String: Any] {
        guard let root = Settings.archive, let machine = statusCache?["machine"] as? [String: Any],
              let vault = machine["vault"] as? String, Settings.archiveKey(root) == Settings.archiveKey(vault) else {
            return ["available": false]
        }
        return ["available": true, "scope": root, "excluded": Settings.backupExclusions(root)]
    }

    private func setBackupScope(_ request: [String: Any], generation: UUID) {
        let state = backupScopeState()
        guard state["available"] as? Bool == true, let root = Settings.archive,
              let requestedRoot = request["root"] as? String,
              Settings.archiveKey(requestedRoot) == Settings.archiveKey(root),
              let host = request["host"] as? String, let node = request["node"] as? String,
              let vmid = request["vmid"] as? String, let required = request["required"] as? Bool,
              let backups = statusCache?["backups"] as? [String: Any],
              let hosts = backups["hosts"] as? [[String: Any]],
              hosts.contains(where: { $0["host"] as? String == host && $0["node"] as? String == node && $0["vmid"] as? String == vmid }) else {
            deliver("backupScope", ["error": "Refresh this archive's backup list before changing its scope."], generation: generation)
            return
        }
        Settings.requireBackup(node + ":" + vmid, required: required, root: root)
        deliver("backupScope", ["host": host, "required": required, "scope": backupScopeState()], generation: generation)
    }

    private func deviceAssociationState() -> [String: Any] {
        guard let root = Settings.archive, let machine = statusCache?["machine"] as? [String: Any],
              let vault = machine["vault"] as? String, Settings.archiveKey(root) == Settings.archiveKey(vault) else {
            return ["available": false]
        }
        let hub = statusCache?["hub"] as? [String: Any] ?? [:]
        let hubAlias = (machine["hub_pointer"] as? String ?? "").components(separatedBy: ":").first ?? ""
        let protected = [machine["host"] as? String ?? "", hubAlias, hub["hub_host"] as? String ?? ""]
            .filter { !$0.isEmpty }
        return ["available": true, "scope": root, "protected_hosts": protected,
                "disassociated": Settings.disassociatedDevices(root)]
    }

    private func setDeviceAssociation(_ request: [String: Any], generation: UUID) {
        let state = deviceAssociationState()
        guard state["available"] as? Bool == true, let root = Settings.archive,
              let requestedRoot = request["root"] as? String,
              Settings.archiveKey(requestedRoot) == Settings.archiveKey(root),
              let name = request["host"] as? String, !name.isEmpty, name.count <= 128,
              let associated = request["associated"] as? Bool else {
            deliver("deviceAssociation", ["error": "Refresh this archive's device list before changing an association."], generation: generation)
            return
        }
        let protected = state["protected_hosts"] as? [String] ?? []
        let fleet = statusCache?["fleet"] as? [String: Any] ?? [:]
        let known = (fleet["hosts"] as? [[String: Any]] ?? []).contains { $0["host"] as? String == name }
        let saved = Settings.disassociatedDevices(root).contains(name)
        guard !protected.contains(where: { $0.caseInsensitiveCompare(name) == .orderedSame }),
              known || (associated && saved) else {
            deliver("deviceAssociation", ["error": "This device cannot be disassociated. The current device and Hub stay associated."], generation: generation)
            return
        }
        Settings.associateDevice(name, associated: associated, root: root)
        deliver("deviceAssociation", ["host": name, "associated": associated], generation: generation)
    }

    private func statusDetail(_ stderr: String) -> String {
        guard let resources = Bundle.main.resourceURL else { return "Diagnostics unavailable." }
        let p = Process(), input = Pipe(), output = Pipe()
        p.executableURL = resources.appendingPathComponent("runtime/bin/python3")
        p.arguments = ["-I", "-B", resources.appendingPathComponent("backend/diagnostics.py").path]
        p.standardInput = input; p.standardOutput = output; p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return "Diagnostics unavailable." }
        do { try input.fileHandleForWriting.write(contentsOf: Data(stderr.utf8)) } catch {}
        try? input.fileHandleForWriting.close()
        let data = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
        return p.terminationStatus == 0 ? String(decoding: data, as: UTF8.self) : "Diagnostics unavailable."
    }

    func run(_ args: [String], environment extra: [String: String] = [:], timeLimit: Double? = nil, isolated: Bool = false, done: @escaping (String, String, Int32) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: args[0])
            p.arguments = Array(args.dropFirst())
            p.environment = isolated ? extra : self.env().merging(extra) { _, new in new }
            let o = Pipe(), e = Pipe()
            p.standardOutput = o; p.standardError = e
            do { try p.run() } catch { done("", "\(error)", -1); return }
            var deadline: DispatchWorkItem?
            if let seconds = timeLimit {
                let stop = DispatchWorkItem {
                    if p.isRunning { p.terminate() }
                    DispatchQueue.global().asyncAfter(deadline: .now() + 1) {
                        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
                    }
                }
                deadline = stop
                DispatchQueue.global().asyncAfter(deadline: .now() + seconds, execute: stop)
            }
            defer { deadline?.cancel() }
            // Drain both pipes concurrently: a large stderr must not block stdout/exit.
            let readers = DispatchGroup(); readers.enter()
            var ed = Data()
            DispatchQueue.global().async { ed = e.fileHandleForReading.readDataToEndOfFile(); readers.leave() }
            let od = o.fileHandleForReading.readDataToEndOfFile()
            readers.wait()
            p.waitUntilExit()
            done(String(data: od, encoding: .utf8) ?? "", String(data: ed, encoding: .utf8) ?? "", p.terminationStatus)
        }
    }

    // A drawer request the bridge will not run still ends its run, so the drawer never waits
    // on a reply that is not coming.
    private func refuse(_ d: [String: Any], _ id: String, _ line: String, generation: UUID) {
        deliver("log", ["id": id, "request": d["request"] ?? NSNull(), "line": line, "state": "end", "exit": 64], generation: generation)
    }

    // Every line names the drawer run that asked for it (the page drops any other run's
    // output) and goes only to the document that asked (a reloaded page never sees it).
    // A run always ends: one that outlives timeLimit (a routed ssh on a dead link holds a
    // producer change, every destination and normal quit) is stopped with its whole process
    // group, since that ssh is a grandchild holding the pipe open, and ends as failed.
    func stream(_ args: [String], id: String, request: Any?, generation: UUID, timeLimit: Double = 900, env extra: [String: String] = [:], completion: ((Int32) -> Void)? = nil) {
        DispatchQueue.global(qos: .userInitiated).async {
            func send(_ fields: [String: Any]) {
                self.deliver("log", fields.merging(["id": id, "request": request ?? NSNull()]) { _, tag in tag }, generation: generation)
            }
            let p = Process()
            p.executableURL = URL(fileURLWithPath: args[0])
            p.arguments = Array(args.dropFirst())
            p.environment = self.env().merging(extra) { _, new in new }
            let o = Pipe()
            p.standardOutput = o; p.standardError = o
            send(["line": "$ " + args.map { $0.hasPrefix("/") ? ($0 as NSString).lastPathComponent : $0 }.joined(separator: " "), "state": "start"])
            o.fileHandleForReading.readabilityHandler = { fh in
                let data = fh.availableData
                if data.isEmpty { return }
                for line in (String(data: data, encoding: .utf8) ?? "").split(separator: "\n", omittingEmptySubsequences: false) {
                    if !line.isEmpty { send(["line": String(line)]) }
                }
            }
            do { try p.run() } catch { DispatchQueue.main.async { completion?(-1) }; send(["line": "failed to start: \(error)", "state": "end", "exit": -1]); return }
            // Process makes the child a process group leader, so -pid reaches its descendants.
            let pid = p.processIdentifier
            var stopped = false
            let stop = DispatchWorkItem {
                stopped = true; kill(-pid, SIGTERM); if p.isRunning { p.terminate() }
                DispatchQueue.global().asyncAfter(deadline: .now() + 2) { kill(-pid, SIGKILL); if p.isRunning { kill(pid, SIGKILL) } }
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + timeLimit, execute: stop)
            p.waitUntilExit()
            stop.cancel()
            o.fileHandleForReading.readabilityHandler = nil
            // after a stop, never wait on a pipe something outside the group may still hold
            let rest = stopped ? Data() : o.fileHandleForReading.readDataToEndOfFile()
            for line in (String(data: rest, encoding: .utf8) ?? "").split(separator: "\n") { send(["line": String(line)]) }
            if stopped { send(["line": "stopped after \(Int(timeLimit / 60)) min without finishing"]) }
            DispatchQueue.main.async { completion?(p.terminationStatus) }
            send(["line": "exit \(p.terminationStatus)", "state": "end", "exit": Int(p.terminationStatus)])
        }
    }

    func deliver(_ kind: String, _ payload: [String: Any], generation: UUID? = nil) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload), let json = String(data: data, encoding: .utf8) else { return }
        let js = "window.sovDeliver && window.sovDeliver(\(jsString(kind)), \(json));"
        DispatchQueue.main.async {
            if let generation = generation, generation != self.generation { return }
            self.web?.evaluateJavaScript(js, completionHandler: nil)
        }
    }

    private func jsString(_ s: String) -> String {
        let data = try! JSONSerialization.data(withJSONObject: [s])
        let arr = String(data: data, encoding: .utf8)!
        return String(arr.dropFirst().dropLast())
    }
}

func log(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

/// AppKit pulls a titled window back until part of it shows on a display; a background
/// snapshot must stay wholly off screen, so QA alone skips that.
final class ConsoleWindow: NSWindow {
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        App.shared.qaBackground ? frameRect : super.constrainFrameRect(frameRect, to: screen)
    }
}

/// SOV_WINDOW=WxH sizes the window for a snapshot; QA only.
func qaFrame(_ f: NSRect) -> NSRect {
    guard let s = ProcessInfo.processInfo.environment["SOV_WINDOW"], let x = s.firstIndex(of: "x"),
          let w = Double(s[..<x]), let h = Double(s[s.index(after: x)...]) else { return f }
    return NSRect(x: f.origin.x, y: f.origin.y, width: w, height: h)
}

@main
final class App: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message
        alert.window.appearance = nil; alert.window.backgroundColor = pageGround
        alert.addButton(withTitle: "Discard"); alert.addButton(withTitle: "Keep editing")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }
    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { showLoadFailure(w) }
    func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) { showLoadFailure(w) }
    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
        syncAppearance()
        guard w === web else { return }
        loadWatchdog?.cancel()
        w.evaluateJavaScript("typeof window.sovDeliver === 'function'") { value, _ in
            if (value as? Bool) == true {
                self.loadingOverlay?.removeFromSuperview(); self.loadingOverlay = nil
                if let place = self.pendingPlace { self.pendingPlace = nil; self.bridge.deliver("goto", place) }
            }
            else { self.showLoadFailure(w) }
        }
    }
    // Handling this callback turns off WebKit's own reload. The window offers Try again;
    // the Glance has no overlay, so it loads again or every later crown click opens it blank.
    func webViewWebContentProcessDidTerminate(_ w: WKWebView) { if w === glanceWeb { load(w, glance: true) } else { showLoadFailure(w) } }
    static var shared: App!
    var window: NSWindow!
    var web: WKWebView!
    var bridge: Bridge!
    var statusItem: NSStatusItem?
    var popover: NSPopover?
    var glanceWeb: WKWebView?
    var glanceBridge: Bridge?
    var sovPath: String?
    var localMode = true
    var pendingPlace: [String: Any]?
    var loadingOverlay: NSView?
    var loadWatchdog: DispatchWorkItem?
    var glanceSize = NSSize(width: 420, height: 468)
    var snapshotting: Bool { !(ProcessInfo.processInfo.environment["SOV_SNAPSHOT"] ?? "").isEmpty }
    var theme: String { NSApp.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? "dark" : "light" }
    var pageGround: NSColor { theme == "dark" ? NSColor(srgbRed: 0, green: 6/255, blue: 15/255, alpha: 1) : NSColor(srgbRed: 250/255, green: 250/255, blue: 247/255, alpha: 1) }
    var appearanceObservation: NSKeyValueObservation?
    var appearanceMenu: NSMenu?
    var qaGlance: Bool { ProcessInfo.processInfo.environment["SOV_GLANCE"] == "1" }
    // Snapshot QA runs behind the owner's work: its window sits past the edge of every
    // screen and the app never takes focus. SOV_QA_FOREGROUND=1 shows it on screen again.
    var qaBackground: Bool { snapshotting && ProcessInfo.processInfo.environment["SOV_QA_FOREGROUND"] != "1" }
    func present() {
        guard qaBackground else { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); return }
        let edge = NSScreen.screens.map(\.frame.maxX).max() ?? 0
        window.setFrameOrigin(NSPoint(x: edge + 400, y: 0)); window.orderFrontRegardless()
    }

    static func main() {
        let app = NSApplication.shared
        let d = App()
        App.shared = d
        app.delegate = d
        app.setActivationPolicy(d.snapshotting || Settings.location == "menubar" ? .accessory : .regular)
        app.run()
    }

    private func makeWeb() -> (WKWebView, Bridge) {
        let b = Bridge(sov: sovPath)
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(b, name: "sov")
        cfg.userContentController.addUserScript(WKUserScript(source: "document.documentElement.dataset.theme='\(theme)';", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        let w = WKWebView(frame: .zero, configuration: cfg)
        w.navigationDelegate = self
        w.uiDelegate = self
        b.web = w
        w.setValue(false, forKey: "drawsBackground")
        return (w, b)
    }

    private func load(_ w: WKWebView, glance: Bool) {
        if w === web { bridge.generation = UUID() } else if w === glanceWeb { glanceBridge?.generation = UUID() }
        // resourceURL is relative to the bundle; resolve it, or URLComponents keeps only the
        // relative part and loadFileURL is handed a path with no scheme that never loads
        guard let ui = Bundle.main.resourceURL?.appendingPathComponent((localMode && !glance) ? "ui/local.html" : "ui/index.html").absoluteURL else { return }
        var comps = URLComponents(url: ui, resolvingAgainstBaseURL: true)!
        comps.fragment = glance ? (qaGlance ? "glance-qa" : "glance") : nil
        let target = comps.url ?? ui
        log("loading \(target.absoluteString)")
        // Refresh the document-start script too: later navigation must not reuse the launch theme.
        let controller = w.configuration.userContentController
        controller.removeAllUserScripts()
        controller.addUserScript(WKUserScript(source: "document.documentElement.dataset.theme='\(theme)';", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let budget = glance ? (glanceBridge?.statusBudget ?? 45) : bridge.statusBudget
        controller.addUserScript(WKUserScript(source: "window.sovStatusBudget=\(budget);", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        w.loadFileURL(target, allowingReadAccessTo: ui.deletingLastPathComponent())
        if w === web {
            let watchdog = DispatchWorkItem { [weak self, weak w] in if let w = w { self?.showLoadFailure(w) } }
            loadWatchdog?.cancel(); loadWatchdog = watchdog
            DispatchQueue.main.asyncAfter(deadline: .now() + 15, execute: watchdog)
        }
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        applyAppearance()
        appearanceObservation = NSApp.observe(\.effectiveAppearance, options: [.new]) { [weak self] _, _ in
            DispatchQueue.main.async { self?.syncAppearance() }
        }
        sovPath = ["\(NSHomeDirectory())/brain-bin/sov", "/usr/local/bin/sov", "/opt/homebrew/bin/sov"].first { FileManager.default.isExecutableFile(atPath: $0) }
        if snapshotting, let command = ProcessInfo.processInfo.environment["SOV_QA_STATUS_COMMAND"] { sovPath = command }
        localMode = true
        buildMenu()
        let (w, b) = makeWeb()
        web = w; bridge = b

        let frame = qaGlance ? NSRect(x: 120, y: 120, width: glanceSize.width, height: glanceSize.height)
                             : NSRect(x: 120, y: 120, width: 900, height: 600)
        window = ConsoleWindow(contentRect: qaFrame(frame), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Sovereign"
        window.appearance = nil; window.backgroundColor = pageGround
        window.minSize = qaGlance ? glanceSize : NSSize(width: 720, height: 460)
        // Keep the native title bar outside WKWebView so AppKit owns window dragging.
        // Web content must retain mouse gestures for controls and text selection.
        let container = NSView(frame: NSRect(origin: .zero, size: frame.size))
        web.frame = container.bounds; web.autoresizingMask = [.width, .height]
        container.addSubview(web); window.contentView = container
        window.isReleasedWhenClosed = false
        if !qaGlance && ProcessInfo.processInfo.environment["SOV_WINDOW"] == nil { window.setFrameAutosaveName("SovereignConsole") }

        applySettings()
        showLoading(message: "Opening your archive…", retry: false)
        // Menu-bar-only installs start quiet: the panel appears when the crown is clicked.
        let snapshotting = !(ProcessInfo.processInfo.environment["SOV_SNAPSHOT"] ?? "").isEmpty
        if Settings.location != "menubar" || snapshotting {
            present()
        }
        // Load after the window is on screen: a web view that loads while hidden may
        // stay suspended, and takeSnapshot on it never returns.
        load(web, glance: qaGlance)

        // QA only: SOV_QA_JS runs one statement in the page a moment after load, so a
        // harness can exercise a path a snapshot anchor cannot reach (the gate, a
        // connect, any bridge command) and photograph what came back.
        if let qajs = ProcessInfo.processInfo.environment["SOV_QA_JS"], !qajs.isEmpty {
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { [weak self] in
                self?.web.evaluateJavaScript(qajs) { _, err in if let e = err { log("SOV_QA_JS: \(e)") } }
            }
        }

        // Design QA without screen-recording permission: SOV_SNAPSHOT=/path.png makes the
        // app photograph its own web view once status has rendered, then quit.
        if let snap = ProcessInfo.processInfo.environment["SOV_SNAPSHOT"], !snap.isEmpty {
            let delay = Double(ProcessInfo.processInfo.environment["SOV_SNAPSHOT_DELAY"] ?? "") ?? 7
            DispatchQueue.main.asyncAfter(deadline: .now() + delay + 20) {
                FileHandle.standardError.write("snapshot watchdog: no frame after \(delay + 20)s, giving up\n".data(using: .utf8)!)
                exit(2)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [self] in
                func save(_ image: NSImage?, _ path: String) {
                    if image == nil { log("snapshot returned no image for \(path)") }
                    if let image = image, let tiff = image.tiffRepresentation,
                       let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) {
                        try? png.write(to: URL(fileURLWithPath: path))
                    }
                }
                web.takeSnapshot(with: nil) { image, err in
                    if let err = err { log("snapshot error: \(err)") }
                    save(image, snap)
                    // second frame: after the anchor (a view, a row, a settings pane, or the bottom)
                    let anchor = ProcessInfo.processInfo.environment["SOV_SNAPSHOT_ANCHOR"] ?? ""
                    self.applySnapshotAnchor(anchor) {
                        let qa = ProcessInfo.processInfo.environment["SOV_QA_JS_AFTER_ANCHOR"] ?? "void 0"
                        self.web.callAsyncJavaScript(qa, arguments: [:], in: nil, in: .page) { result in
                            if case .failure(let error) = result { log("snapshot QA: \(error)"); exit(2) }
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                                self.web.takeSnapshot(with: nil) { image2, error in
                                    if let error = error { log("snapshot error: \(error)") }
                                    save(image2, snap.replacingOccurrences(of: ".png", with: "-bottom.png"))
                                    NSApp.terminate(nil)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private func applySnapshotAnchor(_ anchor: String, done: @escaping () -> Void) {
        let operations = anchor.hasPrefix("operations:view:")
        let home = anchor.hasPrefix("home:view:")
        let value = home ? String(anchor.dropFirst(10)) : operations ? String(anchor.dropFirst(16)) : anchor.hasPrefix("view:") ? String(anchor.dropFirst(5)) : anchor
        let encoded = String(data: try! JSONSerialization.data(withJSONObject: [value]), encoding: .utf8)! + "[0]"
        if operations { navigate(page: "operations", place: ["snapshot": value]) }
        if home { navigate(page: "home", place: ["view": value]) }
        func wait(_ attempt: Int) {
            web.evaluateJavaScript("typeof sovDeliver === 'function' && window.sovSnapshotReady && window.sovSnapshotReady()") { ready, _ in
                if (ready as? Bool) == true && (!operations || (!self.localMode && self.web.url?.lastPathComponent == "index.html")) && (!home || (self.localMode && self.web.url?.lastPathComponent == "local.html")) {
                    let js = operations || home ? "void 0" : anchor.hasPrefix("view:") ? "window.sovView(\(encoded))" : anchor.isEmpty ? "window.scrollTo(0,document.body.scrollHeight)" : "document.querySelector(\(encoded))?.scrollIntoView({block:'start'})"
                    self.web.evaluateJavaScript("document.body.classList.add('qa');" + js) { _, error in
                        if let error = error { log("snapshot anchor: \(error)"); exit(2) }
                        done()
                    }
                } else if attempt >= 100 { log("snapshot anchor did not become ready"); exit(2) }
                else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { wait(attempt + 1) } }
            }
        }
        // Let navigation commit before checking the destination document.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { wait(0) }
    }

    private func showLoading(message: String, retry: Bool) {
        loadingOverlay?.removeFromSuperview()
        guard let content = window?.contentView else { return }
        let panel = NSView(frame: content.bounds); panel.autoresizingMask = [.width, .height]
        panel.wantsLayer = true; panel.layer?.backgroundColor = pageGround.cgColor
        let label = NSTextField(wrappingLabelWithString: message); label.alignment = .center
        label.font = .systemFont(ofSize: 17)
        let stack = NSStackView(views: [label]); stack.orientation = .vertical; stack.spacing = 18
        if retry { stack.addArrangedSubview(NSButton(title: "Try again", target: self, action: #selector(retryLoad))) }
        stack.translatesAutoresizingMaskIntoConstraints = false; panel.addSubview(stack)
        NSLayoutConstraint.activate([stack.centerXAnchor.constraint(equalTo: panel.centerXAnchor), stack.centerYAnchor.constraint(equalTo: panel.centerYAnchor), stack.widthAnchor.constraint(lessThanOrEqualToConstant: 460)])
        content.addSubview(panel); loadingOverlay = panel
    }
    private func showLoadFailure(_ w: WKWebView) {
        log("archive view could not load")
        if w === web { loadWatchdog?.cancel(); showLoading(message: "The archive view could not load. Your files are unchanged.", retry: true) }
    }
    @objc private func retryLoad() { showLoading(message: "Opening your archive…", retry: false); load(web, glance: false) }

    func chooseArchive(create: Bool) {
        let selected: URL?
        if create {
            let panel = NSSavePanel(); panel.title = "Create archive"; panel.nameFieldStringValue = "My Archive"
            panel.prompt = "Create"; panel.canCreateDirectories = false
            selected = panel.runModal() == .OK ? panel.url : nil
        } else {
            let panel = NSOpenPanel(); panel.title = "Open archive"; panel.canChooseDirectories = true
            panel.canChooseFiles = false; panel.allowsMultipleSelection = false
            selected = panel.runModal() == .OK ? panel.url : nil
        }
        guard let url = selected else { return }
        bridge.local(["action": create ? "create" : "open", "root": url.path]) { result in
            DispatchQueue.main.async {
                if let error = result["error"] as? String {
                    let alert = NSAlert(); alert.messageText = "Archive could not be opened"; alert.informativeText = error; alert.window.appearance = nil; alert.window.backgroundColor = self.pageGround; alert.runModal(); return
                }
                guard let root = result["root"] as? String else { return }
                Settings.archive = root
                // The Glance is a second document on its own bridge; it asked once, at load.
                self.bridge.deliver("localState", ["root": root])
                self.glanceBridge?.deliver("localState", ["root": root])
            }
        }
    }

    // ---- appearance: update existing documents, never reload a draft or decision preview ----

    func setAppearance(_ value: String) {
        Settings.appearance = value
        applyAppearance()
    }

    private func applyAppearance() {
        let override = ProcessInfo.processInfo.environment["SOV_APPEARANCE"]
        let value = override.flatMap { Settings.appearances.contains($0) ? $0 : nil } ?? Settings.appearance
        NSApp.appearance = value == "system" ? nil : NSAppearance(named: value == "dark" ? .darkAqua : .aqua)
        syncAppearance()
    }

    private func syncAppearance() {
        window?.backgroundColor = pageGround
        loadingOverlay?.layer?.backgroundColor = pageGround.cgColor
        NSApp.modalWindow?.backgroundColor = pageGround
        // Windows inherit the application, including native sheets and alerts.
        let js = "document.documentElement.dataset.theme='\(theme)';window.dispatchEvent(new CustomEvent('sov-appearance',{detail:'\(Settings.appearance)'}));"
        for view in [web, glanceWeb].compactMap({ $0 }) {
            view.evaluateJavaScript(js, completionHandler: nil)
        }
        for item in appearanceMenu?.items ?? [] {
            item.state = (item.representedObject as? String) == Settings.appearance ? .on : .off
        }
    }

    @objc func chooseAppearance(_ sender: NSMenuItem) {
        if let value = sender.representedObject as? String { setAppearance(value) }
    }

    // ---- settings ----

    func applySettings(loginChanged: Bool = false) {
        let loc = Settings.location
        NSApp.setActivationPolicy(snapshotting || loc == "menubar" ? .accessory : .regular)
        if snapshotting || loc == "dock" {
            if let item = statusItem { NSStatusBar.system.removeStatusItem(item); statusItem = nil }
            popover?.performClose(nil)
        } else if statusItem == nil {
            let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
            item.button?.image = crownImage()
            item.button?.toolTip = "Sovereign"
            item.button?.target = self
            item.button?.action = #selector(toggleGlance(_:))
            statusItem = item
            attachStateDot(to: item)
        }
        Settings.lastError = nil
        if loginChanged, #available(macOS 13, *) {
            do {
                if Settings.loginItem { if SMAppService.mainApp.status != .enabled { try SMAppService.mainApp.register() } }
                else if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() }
            } catch {
                Settings.lastError = "Open at login: \(error.localizedDescription)"
                // Store what macOS has, so the box shows it and ticking it again is a change to retry.
                Settings.loginItem = SMAppService.mainApp.status == .enabled
            }
        }
    }

    func broadcastSettings() {
        bridge?.deliver("settings", Settings.dict(probe: true))
        glanceBridge?.deliver("settings", Settings.dict(probe: true))
    }

    // ---- the state dot beside the crown: 6 px at the lower right, the verdict's colour ----
    var stateDot: NSView?
    var verdictState = "idle"
    static let stateColors: [String: NSColor] = ["live": NSColor(red: 0.18, green: 0.545, blue: 0.341, alpha: 1), "warn": NSColor(red: 0.71, green: 0.506, blue: 0.055, alpha: 1),
                                                 "down": NSColor(red: 0.761, green: 0.231, blue: 0.192, alpha: 1), "idle": NSColor(white: 0.62, alpha: 1)]
    /// The dot wears a 1 px ring in the bar's own colour so it never fuses with the crown's right point.
    private func barColor(for view: NSView?) -> NSColor {
        let dark = view?.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        return dark ? NSColor(white: 0.17, alpha: 1) : NSColor(white: 0.93, alpha: 1)
    }
    func attachStateDot(to item: NSStatusItem) {
        guard let button = item.button else { return }
        let dot = NSView(frame: NSRect(x: button.bounds.width - 9, y: 2, width: 8, height: 8))
        dot.wantsLayer = true; dot.layer?.cornerRadius = 4; dot.autoresizingMask = [.minXMargin]
        dot.layer?.borderWidth = 1; dot.layer?.borderColor = barColor(for: button).cgColor
        dot.layer?.backgroundColor = App.stateColors[verdictState]?.cgColor
        button.addSubview(dot); stateDot = dot
    }
    func setVerdictState(_ state: String) {
        verdictState = state
        stateDot?.layer?.backgroundColor = App.stateColors[state]?.cgColor
        stateDot?.layer?.borderColor = barColor(for: statusItem?.button).cgColor
        statusItem?.button?.toolTip = "Sovereign: \(state)"
    }
    func setGlanceHeight(_ h: Double) {
        let hh = max(284, min(h, 640))
        glanceSize.height = hh
        popover?.contentSize = NSSize(width: 420, height: hh)
        if qaGlance { window.setContentSize(NSSize(width: 420, height: hh)) }
    }
    /// QA: SOV_STATUS_SNAPSHOT=<dir> writes the status item at 1x and 2x on light and dark bars.
    func snapshotStatusItem(_ dir: String) {
        let glyph = crownImage(), current = verdictState
        defer { verdictState = current }
        for st in ["live", "warn", "down"] { verdictState = st; snapshotStatusItemOnce(dir, glyph) }
    }
    private func snapshotStatusItemOnce(_ dir: String, _ glyph: NSImage) {
        for (bar, bg, ink) in [("light", NSColor(white: 0.93, alpha: 1), NSColor.black), ("dark", NSColor(white: 0.17, alpha: 1), NSColor.white)] {
            for scale in [1, 2] {
                let w = 22, h = 22
                let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w * scale, pixelsHigh: h * scale, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
                rep.size = NSSize(width: w, height: h)
                NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
                bg.setFill(); NSRect(x: 0, y: 0, width: w, height: h).fill()
                let tinted = glyph.copy() as! NSImage; tinted.isTemplate = false
                tinted.lockFocus(); ink.set(); NSRect(origin: .zero, size: tinted.size).fill(using: .sourceAtop); tinted.unlockFocus()
                tinted.draw(in: NSRect(x: 2, y: 2, width: 18, height: 18))
                bg.setFill(); NSBezierPath(ovalIn: NSRect(x: 13, y: 2, width: 8, height: 8)).fill()
                (App.stateColors[verdictState] ?? .gray).setFill(); NSBezierPath(ovalIn: NSRect(x: 14, y: 3, width: 6, height: 6)).fill()
                NSGraphicsContext.restoreGraphicsState()
                if let png = rep.representation(using: .png, properties: [:]) { try? png.write(to: URL(fileURLWithPath: "\(dir)/status-\(bar)-\(verdictState)@\(scale)x.png")) }
            }
        }
    }
    private func crownImage() -> NSImage {
        // The design's template glyph when the bundle carries it; the drawn crown otherwise.
        if let named = NSImage(named: "MenuBarTemplate") { named.isTemplate = true; return named }
        // The same crown as the UI, drawn as a template image so it follows the menu bar's ink.
        let img = NSImage(size: NSSize(width: 18, height: 18), flipped: true) { _ in
            let p = NSBezierPath()
            let s: CGFloat = 18.0 / 24.0
            func pt(_ x: CGFloat, _ y: CGFloat) -> NSPoint { NSPoint(x: x * s, y: y * s) }
            p.move(to: pt(3, 16)); p.line(to: pt(4.5, 7)); p.line(to: pt(9, 11)); p.line(to: pt(12, 5))
            p.line(to: pt(15, 11)); p.line(to: pt(19.5, 7)); p.line(to: pt(21, 16)); p.close()
            p.appendRect(NSRect(x: 3 * s, y: 18 * s, width: 18 * s, height: 2.2 * s))
            NSColor.black.setFill(); p.fill()
            return true
        }
        img.isTemplate = true
        return img
    }

    // ---- glance ----

    @objc func toggleGlance(_ sender: Any?) {
        if let p = popover, p.isShown { p.performClose(nil); return }
        prepareGlance()
        guard let button = statusItem?.button, let p = popover else { return }
        glanceWeb?.evaluateJavaScript("window.sovRefresh && window.sovRefresh();", completionHandler: nil)
        p.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        NSApp.activate(ignoringOtherApps: true)
    }

    func prepareGlance() {
        if glanceWeb == nil {
            let (w, b) = makeWeb()
            w.frame = NSRect(origin: .zero, size: glanceSize)
            glanceWeb = w; glanceBridge = b
            load(w, glance: true)
            let vc = NSViewController()
            vc.view = w
            let p = NSPopover()
            p.behavior = .transient
            p.contentSize = glanceSize
            p.contentViewController = vc
            popover = p
        }
    }

    func navigate(page: String, place: [String: Any]? = nil) {
        let wantsLocal = page == "home"
        let destination = place ?? ["view": page == "review" ? "review" : wantsLocal ? "home" : "glance"]
        if wantsLocal == localMode {
            bridge.deliver("goto", destination)
            return
        }
        web.evaluateJavaScript("window.sovCanQuit ? window.sovCanQuit() : true") { result, error in
            guard error == nil, (result as? Bool) == true else { return }
            self.localMode = wantsLocal
            self.pendingPlace = destination
            self.showLoading(message: wantsLocal ? "Opening your archive…" : "Reading connected system…", retry: false)
            self.load(self.web, glance: false)
        }
    }

    func showConsole(place: [String: Any]?) {
        popover?.performClose(nil)
        if qaGlance { return }
        present()
        // Today lives in the other document; every other place is a view of this one.
        // The Glance's verdict and jump-less rows name Today as "glance", as setView does.
        if let place = place {
            if ["today", "glance", "home"].contains(place["view"] as? String ?? "") { navigate(page: "home", place: ["view": "home"]) }
            else { navigate(page: "operations", place: place) }
        }
    }

    // Only quit on close when the owner asked for it, and only when there is no menu bar
    // crown left to run under. Reopen (Dock click, or the crown) brings the window back.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        Settings.location == "dock" && Settings.closeQuits
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard web != nil else { return .terminateNow }
        web.evaluateJavaScript("window.sovCanQuit ? window.sovCanQuit() : true") { result, error in
            let allowed = error != nil || (result as? Bool) == true
            if self.snapshotting { log("native quit decision: \(allowed ? "allowed" : "blocked")") }
            // The page says what is holding it; a closed window would hide that.
            if !allowed { self.window.makeKeyAndOrderFront(nil) }
            sender.reply(toApplicationShouldTerminate: allowed)
        }
        return .terminateLater
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { window.makeKeyAndOrderFront(nil) }
        return true
    }

    private func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Sovereign", action: #selector(showIntroduction), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Settings…", action: #selector(openSettings), keyEquivalent: ",")
        appMenu.addItem(withTitle: "Refresh", action: #selector(refresh), keyEquivalent: "r")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Sovereign", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Sovereign", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        // Cmd+W, Cmd+M and Cmd+H reach AppKit only as menu key equivalents.
        let fileItem = NSMenuItem(); main.addItem(fileItem)
        let file = NSMenu(title: "File")
        if localMode {
            file.addItem(withTitle: "Today", action: #selector(openHome), keyEquivalent: "")
            file.addItem(withTitle: "New Archive…", action: #selector(newArchive), keyEquivalent: "")
            file.addItem(withTitle: "Open Archive…", action: #selector(openArchive), keyEquivalent: "o")
            file.addItem(.separator())
        }
        file.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileItem.submenu = file
        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let viewMenu = NSMenu(title: "View")
        let appearanceItem = NSMenuItem(title: "Appearance", action: nil, keyEquivalent: "")
        let choices = NSMenu(title: "Appearance")
        for value in Settings.appearances {
            let item = NSMenuItem(title: value.capitalized, action: #selector(chooseAppearance(_:)), keyEquivalent: "")
            item.target = self; item.representedObject = value
            item.state = value == Settings.appearance ? .on : .off
            choices.addItem(item)
        }
        appearanceItem.submenu = choices; appearanceMenu = choices
        viewMenu.addItem(appearanceItem); viewItem.submenu = viewMenu
        let windowItem = NSMenuItem(); main.addItem(windowItem)
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowItem.submenu = windowMenu; NSApp.windowsMenu = windowMenu
        NSApp.mainMenu = main
    }

    @objc func showIntroduction() {
        guard let resources = Bundle.main.resourceURL else { return }
        let executable = resources.appendingPathComponent("runtime/bin/python3").path
        let script = resources.appendingPathComponent("backend/bin/sov-about").path
        bridge.run([executable, script], timeLimit: 5) { out, _, code in
            DispatchQueue.main.async {
                let alert = NSAlert()
                alert.messageText = "Sovereign"
                alert.informativeText = code == 0 ? out : "Your owned archive. Local setup could not be read. Open Settings to inspect this installation."
                alert.addButton(withTitle: "Done")
                alert.runModal()
            }
        }
    }

    @objc func refresh() { web.evaluateJavaScript("window.sovRefresh && window.sovRefresh();", completionHandler: nil) }
    @objc func openSettings() { showConsole(place: ["settings": true]) }
    @objc func openHome() { navigate(page: "home") }
    @objc func newArchive() { navigate(page: "home", place: ["chooseArchive": true, "create": true]) }
    @objc func openArchive() { navigate(page: "home", place: ["chooseArchive": true, "create": false]) }
}
