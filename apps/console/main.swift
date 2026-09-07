// Sovereign console: a thin native shell around `sov status --json`.
//
// Two ways in, one UI. The window is the full console. The menu-bar item pops a
// small Glance panel (the same ui/index.html loaded with #glance) that shows the
// numbers that move and opens the window at the right place. A bridge per web
// view runs `sov`, streams command output, and hands JSON back. The app never
// writes the vault; the gate goes through `sov gate`, connectors through
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

    init(sov: String?) { self.sov = sov }

    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard let d = m.body as? [String: Any], let cmd = d["cmd"] as? String else { return }
        switch cmd {
        case "status":
            guard let sov = sov else { deliver("status", ["error": "sov not found: connect this machine first (sov connect <tool> --apply)"]); return }
            var args = [sov, "status", "--json"]
            if (d["hub"] as? Bool) == false { args.append("--no-hub") }
            run(args) { out, err, code in
                if let data = out.data(using: .utf8), let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    self.deliver("status", obj)
                } else {
                    self.deliver("status", ["error": "sov status failed (exit \(code)): \(err.suffix(400))"])
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
            run(["/bin/launchctl", "kickstart", "-k", "gui/\(getuid())/\(label)"]) { out, err, code in
                self.deliver("kickstart", ["label": label, "exit": code, "out": out + err])
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
        case "gate":
            // The owner's gate. Runs `sov gate <verb> <slug>` where the hub lives: over ssh
            // when ~/.brain-hub points elsewhere, locally when this machine is the hub.
            // Inputs are whitelisted before they touch a shell: the verb is one of two
            // words, the slug is kebab-case, the alias is a hostname, the reason is quoted.
            guard let verb = d["verb"] as? String, ["approve", "reject"].contains(verb),
                  let slug = d["slug"] as? String,
                  slug.range(of: "^[a-z0-9][a-z0-9-]{0,120}$", options: .regularExpression) != nil else { return }
            let reason = String(((d["reason"] as? String) ?? "").replacingOccurrences(of: "'", with: "").prefix(200))
            let via = (d["via"] as? String) ?? "local"
            if via.hasPrefix("ssh "), let alias = via.split(separator: " ").last.map(String.init),
               alias.range(of: "^[A-Za-z0-9._-]+$", options: .regularExpression) != nil {
                let remote = "PATH=\"$HOME/brain-bin:$HOME/.local/bin:$PATH\" sov gate \(verb) \(slug) '\(reason)'"
                stream(["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", alias, remote], id: "gate")
            } else if let sov = sov {
                stream([sov, "gate", verb, slug, reason], id: "gate")
            }
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

    func run(_ args: [String], done: @escaping (String, String, Int32) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: args[0])
            p.arguments = Array(args.dropFirst())
            p.environment = self.env()
            let o = Pipe(), e = Pipe()
            p.standardOutput = o; p.standardError = e
            do { try p.run() } catch { done("", "\(error)", -1); return }
            let od = o.fileHandleForReading.readDataToEndOfFile()
            let ed = e.fileHandleForReading.readDataToEndOfFile()
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

    func deliver(_ kind: String, _ payload: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload), let json = String(data: data, encoding: .utf8) else { return }
        let js = "window.sovDeliver && window.sovDeliver(\(jsString(kind)), \(json));"
        DispatchQueue.main.async { self.web?.evaluateJavaScript(js, completionHandler: nil) }
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
final class App: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { log("navigation failed: \(e)") }
    func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) { log("navigation failed late: \(e)") }
    func webView(_ w: WKWebView, didFinish n: WKNavigation!) { log("loaded \(w.url?.absoluteString ?? "?")") }
    func webViewWebContentProcessDidTerminate(_ w: WKWebView) { log("web content process terminated") }
    static var shared: App!
    var window: NSWindow!
    var web: WKWebView!
    var bridge: Bridge!
    var statusItem: NSStatusItem?
    var popover: NSPopover?
    var glanceWeb: WKWebView?
    var glanceBridge: Bridge?
    var sovPath: String?
    var glanceSize = NSSize(width: 420, height: 468)
    var qaGlance: Bool { ProcessInfo.processInfo.environment["SOV_GLANCE"] == "1" }

    static func main() {
        let app = NSApplication.shared
        let d = App()
        App.shared = d
        app.delegate = d
        app.setActivationPolicy(Settings.location == "menubar" ? .accessory : .regular)
        app.run()
    }

    private func makeWeb() -> (WKWebView, Bridge) {
        let b = Bridge(sov: sovPath)
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(b, name: "sov")
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        let w = WKWebView(frame: .zero, configuration: cfg)
        w.navigationDelegate = self
        b.web = w
        w.setValue(false, forKey: "drawsBackground")
        return (w, b)
    }

    private func load(_ w: WKWebView, glance: Bool) {
        // resourceURL is relative to the bundle; resolve it, or URLComponents keeps only the
        // relative part and loadFileURL is handed a path with no scheme that never loads
        guard let ui = Bundle.main.resourceURL?.appendingPathComponent("ui/index.html").absoluteURL else { return }
        var comps = URLComponents(url: ui, resolvingAgainstBaseURL: true)!
        comps.fragment = glance ? (qaGlance ? "glance-qa" : "glance") : nil
        let target = comps.url ?? ui
        log("loading \(target.absoluteString)")
        w.loadFileURL(target, allowingReadAccessTo: ui.deletingLastPathComponent())
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        buildMenu()
        // SOV_APPEARANCE=dark|light forces the appearance (used with SOV_SNAPSHOT for design QA).
        if let a = ProcessInfo.processInfo.environment["SOV_APPEARANCE"] {
            NSApp.appearance = NSAppearance(named: a == "dark" ? .darkAqua : .aqua)
        }
        sovPath = ["\(NSHomeDirectory())/brain-bin/sov", "/usr/local/bin/sov", "/opt/homebrew/bin/sov"].first { FileManager.default.isExecutableFile(atPath: $0) }
        let (w, b) = makeWeb()
        web = w; bridge = b

        let frame = qaGlance ? NSRect(x: 120, y: 120, width: glanceSize.width, height: glanceSize.height)
                             : NSRect(x: 120, y: 120, width: 900, height: 600)
        window = NSWindow(contentRect: qaFrame(frame), styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.title = "Sovereign"
        window.minSize = qaGlance ? glanceSize : NSSize(width: 720, height: 460)
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.isMovableByWindowBackground = true
        window.contentView = web
        window.isReleasedWhenClosed = false
        if !qaGlance && ProcessInfo.processInfo.environment["SOV_WINDOW"] == nil { window.setFrameAutosaveName("SovereignConsole") }

        applySettings()
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
                    let js: String
                    if anchor.hasPrefix("view:") {
                        js = "window.sovView && window.sovView(\"\(anchor.dropFirst(5))\");"
                    } else if anchor.isEmpty {
                        js = "window.scrollTo(0, document.body.scrollHeight);"
                    } else {
                        js = "var el=document.querySelector(\"\(anchor)\"); if(el){el.scrollIntoView({block:'start'});} else {window.scrollTo(0, document.body.scrollHeight);}"
                    }
                    self.web.evaluateJavaScript("document.body.classList.add('qa');" + js) { _, _ in
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                            self.web.takeSnapshot(with: nil) { image2, _ in
                                save(image2, snap.replacingOccurrences(of: ".png", with: "-bottom.png"))
                                NSApp.terminate(nil)
                            }
                        }
                    }
                }
            }
        }
    }

    // ---- settings ----

    func applySettings(loginChanged: Bool = false) {
        let loc = Settings.location
        NSApp.setActivationPolicy(loc == "menubar" ? .accessory : .regular)
        if loc == "dock" {
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

    func showConsole(place: [String: Any]?) {
        popover?.performClose(nil)
        if qaGlance { return }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if let place = place { bridge.deliver("goto", place) }
    }

    // Only quit on close when the owner asked for it, and only when there is no menu bar
    // crown left to run under. Reopen (Dock click, or the crown) brings the window back.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        Settings.location == "dock" && Settings.closeQuits
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
        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        NSApp.mainMenu = main
    }

    @objc func refresh() { web.evaluateJavaScript("window.sovRefresh && window.sovRefresh();", completionHandler: nil) }
    @objc func openSettings() { showConsole(place: ["settings": true]) }
}
