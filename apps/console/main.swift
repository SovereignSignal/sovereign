// Sovereign console: a thin native shell around `sov status --json`.
//
// Two ways in, one UI. The window is the full console. The menu-bar item pops a
// small Glance panel (the same ui/index.html loaded with #glance) that shows the
// numbers that move and opens the window at the right place. A bridge per web
// view runs `sov`, streams command output, and hands JSON back. The app never
// promotes knowledge automatically; local captures use the bundled archive engine.
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
    static let d = UserDefaults.standard
    static var location: String { get { d.string(forKey: "sov.where") ?? "dock" } set { d.set(newValue, forKey: "sov.where") } }
    static var loginItem: Bool { get { d.bool(forKey: "sov.loginItem") } set { d.set(newValue, forKey: "sov.loginItem") } }
    static var refresh: Int { get { let v = d.integer(forKey: "sov.refresh"); return v > 0 ? v : 60 } set { d.set(newValue, forKey: "sov.refresh") } }
    static var defaultView: String { get { d.string(forKey: "sov.defaultView") ?? "glance" } set { d.set(newValue, forKey: "sov.defaultView") } }
    // Closing the window keeps Sovereign running by default: it is a monitor, and the
    // owner closing a window is not the owner asking the watch to stop. Opt in to quit.
    static var closeQuits: Bool { get { d.bool(forKey: "sov.closeQuits") } set { d.set(newValue, forKey: "sov.closeQuits") } }
    static var lastError: String? = nil
    static var archive: String? { get { d.string(forKey: "sov.archive") } set { d.set(newValue, forKey: "sov.archive") } }

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
                                  "refresh": refresh, "defaultView": defaultView, "closeQuits": closeQuits,
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
            guard let action = d["action"] as? String, ["list", "read", "capture", "context"].contains(action),
                  let root = Settings.archive else { return }
            var request = d
            request["root"] = root
            local(request) { result in
                var response = result
                response["action"] = action; response["request"] = d["request"]
                self.deliver("local", response, generation: generation)
            }
        case "navigate":
            guard let page = d["page"] as? String, ["home", "operations"].contains(page) else { return }
            DispatchQueue.main.async { App.shared.navigate(page: page, place: d["place"] as? [String: Any]) }
        case "status":
            guard let sov = sov else {
                var response: [String: Any] = ["machine": ["connected": false], "available": false]
                response["request"] = d["request"]
                deliver("status", response, generation: generation); return
            }
            var args = [sov, "status", "--json"]
            if (d["hub"] as? Bool) == false { args.append("--no-hub") }
            run(args) { out, err, code in
                if let data = out.data(using: .utf8), let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    var response = obj; response["request"] = d["request"]
                    self.deliver("status", response, generation: generation)
                } else {
                    let detail = self.statusDetail(err)
                    log("status failed (exit \(code)): \(detail)")
                    var response: [String: Any] = ["error": "System status could not be read. Retry or inspect Operations.", "detail": detail]
                    response["request"] = d["request"]
                    self.deliver("status", response, generation: generation)
                }
            }
        case "connect":
            guard let sov = sov, let h = d["harness"] as? String else { return }
            var args = [sov, "connect", h]
            for (flag, key) in [("--host", "host"), ("--vault", "vault"), ("--core", "core"), ("--hub", "hub")] {
                if let v = d[key] as? String, !v.isEmpty { args += [flag, v] }
            }
            if (d["apply"] as? Bool) == true { args.append("--apply") }
            // a secret rides in the child's environment only: never on argv, never in the log
            var secretEnv: [String: String] = [:]
            if let v = d["secret"] as? String, let k = d["secretEnv"] as? String, !v.isEmpty,
               k.range(of: "^[A-Z_][A-Z0-9_]*$", options: .regularExpression) != nil { secretEnv[k] = v }
            stream(args, id: "connect", env: secretEnv)
        case "hostadd":
            // the hub does the work (sov routes there); the drawer streams it
            guard let sov = sov, let name = d["name"] as? String,
                  name.range(of: "^[a-z0-9][a-z0-9-]{1,40}$", options: .regularExpression) != nil else { return }
            var args = [sov, "host", "add", name]
            for (flag, key) in [("--user", "user"), ("--addr", "addr"), ("--identity", "identity"), ("--workstreams", "workstreams")] {
                if let v = d[key] as? String, !v.isEmpty { args += [flag, v] }
            }
            if (d["apply"] as? Bool) == true { args.append("--apply") }
            stream(args, id: "hostadd")
        case "vmstart":
            guard let name = d["name"] as? String, !name.isEmpty else { return }
            run(["/usr/local/bin/prlctl", "start", name]) { out, err, code in
                self.deliver("vmstart", ["name": name, "exit": code, "out": out + err])
            }
        case "kickstart":
            guard let label = d["label"] as? String else { return }
            // A lane row asks for ITS lane, not the whole job. The shared runner takes --only, so
            // run that directly: kickstarting the job would kill the tick in flight (-k) and then
            // run every lane, which is not what the row said it would do. The runner sits beside
            // the sov binary. Anything without a lane is still a whole-job kickstart.
            let lane = (d["lane"] as? String).flatMap { l in
                l.range(of: "^[a-z0-9][a-z0-9-]{0,60}$", options: .regularExpression) != nil ? l : nil
            }
            let runner = sov.map { URL(fileURLWithPath: $0).deletingLastPathComponent()
                                       .appendingPathComponent("sov-connectors-run").path }
            if let lane = lane, let runner = runner, FileManager.default.isExecutableFile(atPath: runner) {
                run([runner, "--only", lane]) { out, err, code in
                    self.deliver("kickstart", ["label": lane, "exit": code, "out": out + err])
                }
            } else {
                run(["/bin/launchctl", "kickstart", "-k", "gui/\(getuid())/\(label)"]) { out, err, code in
                    self.deliver("kickstart", ["label": label, "exit": code, "out": out + err])
                }
            }
        case "clearlog":
            if let p = d["path"] as? String, p.hasSuffix(".log"), p.hasPrefix(NSHomeDirectory()) {
                try? "".write(toFile: p, atomically: true, encoding: .utf8)
                deliver("kickstart", ["label": "cleared " + (p as NSString).lastPathComponent, "exit": 0, "out": ""])
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
            if let u = d["url"] as? String, let url = URL(string: u) { NSWorkspace.shared.open(url) }
        case "gateCheck", "gate":
            guard let slug = d["slug"] as? String,
                  slug.range(of: "^[a-z0-9][a-z0-9-]{0,120}$", options: .regularExpression) != nil,
                  let request = d["request"] as? String, request.count < 100 else { return }
            let mode = cmd == "gateCheck" ? "check" : (d["verb"] as? String ?? "")
            guard ["check", "approve", "reject"].contains(mode) else { return }
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
        case "copyText":
            guard let text = d["text"] as? String, text.utf8.count <= 16000 else { return }
            NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string)
        case "settings":
            deliver("settings", Settings.dict(probe: (d["probe"] as? Bool) == true))
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
            p.arguments = ["-I", "-B", resources.appendingPathComponent("backend/bin/brain-local").path]
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

    func run(_ args: [String], environment extra: [String: String] = [:], done: @escaping (String, String, Int32) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: args[0])
            p.arguments = Array(args.dropFirst())
            p.environment = self.env().merging(extra) { _, new in new }
            let o = Pipe(), e = Pipe()
            p.standardOutput = o; p.standardError = e
            do { try p.run() } catch { done("", "\(error)", -1); return }
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

    func stream(_ args: [String], id: String, env extra: [String: String] = [:]) {
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: args[0])
            p.arguments = Array(args.dropFirst())
            p.environment = self.env().merging(extra) { _, new in new }
            let o = Pipe()
            p.standardOutput = o; p.standardError = o
            self.deliver("log", ["id": id, "line": "$ " + args.map { $0.hasPrefix("/") ? ($0 as NSString).lastPathComponent : $0 }.joined(separator: " "), "state": "start"])
            o.fileHandleForReading.readabilityHandler = { fh in
                let data = fh.availableData
                if data.isEmpty { return }
                for line in (String(data: data, encoding: .utf8) ?? "").split(separator: "\n", omittingEmptySubsequences: false) {
                    if !line.isEmpty { self.deliver("log", ["id": id, "line": String(line)]) }
                }
            }
            do { try p.run() } catch { self.deliver("log", ["id": id, "line": "failed to start: \(error)", "state": "end", "exit": -1]); return }
            p.waitUntilExit()
            o.fileHandleForReading.readabilityHandler = nil
            let rest = o.fileHandleForReading.readDataToEndOfFile()
            for line in (String(data: rest, encoding: .utf8) ?? "").split(separator: "\n") { self.deliver("log", ["id": id, "line": String(line)]) }
            self.deliver("log", ["id": id, "line": "exit \(p.terminationStatus)", "state": "end", "exit": Int(p.terminationStatus)])
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
        alert.window.appearance = NSApp.effectiveAppearance; alert.window.backgroundColor = pageGround
        alert.addButton(withTitle: "Discard"); alert.addButton(withTitle: "Keep editing")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }
    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { showLoadFailure(w) }
    func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) { showLoadFailure(w) }
    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
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
    func webViewWebContentProcessDidTerminate(_ w: WKWebView) { showLoadFailure(w) }
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
    var qaGlance: Bool { ProcessInfo.processInfo.environment["SOV_GLANCE"] == "1" }

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
        w.loadFileURL(target, allowingReadAccessTo: ui.deletingLastPathComponent())
        if w === web {
            let watchdog = DispatchWorkItem { [weak self, weak w] in if let w = w { self?.showLoadFailure(w) } }
            loadWatchdog?.cancel(); loadWatchdog = watchdog
            DispatchQueue.main.asyncAfter(deadline: .now() + 15, execute: watchdog)
        }
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        // SOV_APPEARANCE=dark|light forces the appearance (used with SOV_SNAPSHOT for design QA).
        let appearance = ProcessInfo.processInfo.environment["SOV_APPEARANCE"] ?? "dark"
        NSApp.appearance = NSAppearance(named: appearance == "light" ? .aqua : .darkAqua)
        sovPath = ["\(NSHomeDirectory())/brain-bin/sov", "/usr/local/bin/sov", "/opt/homebrew/bin/sov"].first { FileManager.default.isExecutableFile(atPath: $0) }
        if snapshotting, let command = ProcessInfo.processInfo.environment["SOV_QA_STATUS_COMMAND"] { sovPath = command }
        localMode = true
        buildMenu()
        let (w, b) = makeWeb()
        web = w; bridge = b

        let frame = qaGlance ? NSRect(x: 120, y: 120, width: glanceSize.width, height: glanceSize.height)
                             : NSRect(x: 120, y: 120, width: 900, height: 600)
        window = NSWindow(contentRect: qaFrame(frame), styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.title = "Sovereign"
        window.appearance = NSApp.effectiveAppearance; window.backgroundColor = pageGround
        window.minSize = qaGlance ? glanceSize : NSSize(width: 720, height: 460)
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.isMovableByWindowBackground = true
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
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
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
        let value = operations ? String(anchor.dropFirst(16)) : anchor.hasPrefix("view:") ? String(anchor.dropFirst(5)) : anchor
        let encoded = String(data: try! JSONSerialization.data(withJSONObject: [value]), encoding: .utf8)! + "[0]"
        if operations { navigate(page: "operations", place: ["snapshot": value]) }
        func wait(_ attempt: Int) {
            web.evaluateJavaScript("typeof sovDeliver === 'function' && window.sovSnapshotReady && window.sovSnapshotReady()") { ready, _ in
                if (ready as? Bool) == true && (!operations || (!self.localMode && self.web.url?.lastPathComponent == "index.html")) {
                    let js = operations ? "void 0" : anchor.hasPrefix("view:") ? "window.sovView(\(encoded))" : anchor.isEmpty ? "window.scrollTo(0,document.body.scrollHeight)" : "document.querySelector(\(encoded))?.scrollIntoView({block:'start'})"
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
                    let alert = NSAlert(); alert.messageText = "Archive could not be opened"; alert.informativeText = error; alert.window.appearance = NSApp.effectiveAppearance; alert.window.backgroundColor = self.pageGround; alert.runModal(); return
                }
                guard let root = result["root"] as? String else { return }
                Settings.archive = root
                self.bridge.deliver("localState", ["root": root])
            }
        }
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
        guard let button = statusItem?.button, let p = popover else { return }
        glanceWeb?.evaluateJavaScript("window.sovRefresh && window.sovRefresh();", completionHandler: nil)
        p.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        NSApp.activate(ignoringOtherApps: true)
    }

    func navigate(page: String, place: [String: Any]? = nil) {
        let wantsLocal = page == "home"
        if wantsLocal == localMode {
            bridge.deliver("goto", place ?? ["view": "home"])
            return
        }
        web.evaluateJavaScript("window.sovCanQuit ? window.sovCanQuit() : true") { result, error in
            guard error == nil, (result as? Bool) == true else { return }
            self.localMode = wantsLocal
            self.pendingPlace = place
            self.showLoading(message: wantsLocal ? "Opening your archive…" : "Reading connected system…", retry: false)
            self.load(self.web, glance: false)
        }
    }

    func showConsole(place: [String: Any]?) {
        popover?.performClose(nil)
        if qaGlance { return }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if let place = place { navigate(page: "operations", place: place) }
    }

    // Only quit on close when the owner asked for it, and only when there is no menu bar
    // crown left to run under. Reopen (Dock click, or the crown) brings the window back.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        Settings.location == "dock" && Settings.closeQuits
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard localMode, web != nil else { return .terminateNow }
        web.evaluateJavaScript("window.sovCanQuit ? window.sovCanQuit() : true") { result, error in
            sender.reply(toApplicationShouldTerminate: error != nil || (result as? Bool) == true)
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
        appMenu.addItem(withTitle: "About Sovereign", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Settings…", action: #selector(openSettings), keyEquivalent: ",")
        appMenu.addItem(withTitle: "Refresh", action: #selector(refresh), keyEquivalent: "r")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Sovereign", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        if localMode {
            let fileItem = NSMenuItem(); main.addItem(fileItem)
            let file = NSMenu(title: "File")
            file.addItem(withTitle: "Home", action: #selector(openHome), keyEquivalent: "1")
            file.addItem(withTitle: "New Capture", action: #selector(newCapture), keyEquivalent: "n")
            file.addItem(withTitle: "New Archive…", action: #selector(newArchive), keyEquivalent: "")
            file.addItem(withTitle: "Open Archive…", action: #selector(openArchive), keyEquivalent: "o")
            fileItem.submenu = file
        }
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
        NSApp.mainMenu = main
    }

    @objc func refresh() { web.evaluateJavaScript("window.sovRefresh && window.sovRefresh();", completionHandler: nil) }
    @objc func openSettings() { showConsole(place: ["settings": true]) }
    @objc func openHome() { navigate(page: "home") }
    @objc func newCapture() { navigate(page: "home", place: ["capture": true]) }
    @objc func newArchive() { navigate(page: "home", place: ["chooseArchive": true, "create": true]) }
    @objc func openArchive() { navigate(page: "home", place: ["chooseArchive": true, "create": false]) }
}
