// Sovereign console: a thin native shell around `sov status --json`.
//
// One window, one WKWebView, one bridge. The UI (ui/index.html) asks for
// status, the shell runs `sov`, and hands the JSON back. Actions the UI can
// request: refresh, connect a tool (dry run, then --apply), run a mirror now,
// reveal a lane in Finder, open a URL. Nothing else. The app never writes the
// vault; every change goes through the same `sov connect` the terminal uses.
//
// Build: apps/console/build.sh (swiftc, no Xcode project needed).
import Cocoa
import WebKit

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
            stream(args, id: "connect")
        case "kickstart":
            guard let label = d["label"] as? String else { return }
            run(["/bin/launchctl", "kickstart", "-k", "gui/\(getuid())/\(label)"]) { out, err, code in
                self.deliver("kickstart", ["label": label, "exit": code, "out": out + err])
            }
        case "reveal":
            if let p = d["path"] as? String { NSWorkspace.shared.selectFile(p, inFileViewerRootedAtPath: "") }
        case "open":
            if let p = d["path"] as? String { NSWorkspace.shared.open(URL(fileURLWithPath: p)) }
        case "openurl":
            if let u = d["url"] as? String, let url = URL(string: u) { NSWorkspace.shared.open(url) }
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

    func stream(_ args: [String], id: String) {
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: args[0])
            p.arguments = Array(args.dropFirst())
            p.environment = self.env()
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

@main
final class App: NSObject, NSApplicationDelegate {
    static var shared: App!
    var window: NSWindow!
    var web: WKWebView!
    var bridge: Bridge!

    static func main() {
        let app = NSApplication.shared
        let d = App()
        App.shared = d
        app.delegate = d
        app.setActivationPolicy(.regular)
        app.run()
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        buildMenu()
        // SOV_APPEARANCE=dark|light forces the appearance (used with SOV_SNAPSHOT for design QA).
        if let a = ProcessInfo.processInfo.environment["SOV_APPEARANCE"] {
            NSApp.appearance = NSAppearance(named: a == "dark" ? .darkAqua : .aqua)
        }
        let sovPath = ["\(NSHomeDirectory())/brain-bin/sov", "/usr/local/bin/sov", "/opt/homebrew/bin/sov"].first { FileManager.default.isExecutableFile(atPath: $0) }
        bridge = Bridge(sov: sovPath)
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(bridge, name: "sov")
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        web = WKWebView(frame: .zero, configuration: cfg)
        bridge.web = web
        web.setValue(false, forKey: "drawsBackground")

        let frame = NSRect(x: 120, y: 120, width: 1080, height: 760)
        window = NSWindow(contentRect: frame, styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Sovereign"
        window.minSize = NSSize(width: 820, height: 520)
        window.titlebarAppearsTransparent = true
        window.contentView = web
        window.setFrameAutosaveName("SovereignConsole")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        if let ui = Bundle.main.resourceURL?.appendingPathComponent("ui/index.html") {
            web.loadFileURL(ui, allowingReadAccessTo: ui.deletingLastPathComponent())
        }

        // Design QA without screen-recording permission: SOV_SNAPSHOT=/path.png makes the
        // app photograph its own web view once status has rendered, then quit.
        if let snap = ProcessInfo.processInfo.environment["SOV_SNAPSHOT"], !snap.isEmpty {
            let delay = Double(ProcessInfo.processInfo.environment["SOV_SNAPSHOT_DELAY"] ?? "") ?? 7
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [self] in
                func save(_ image: NSImage?, _ path: String) {
                    if let image = image, let tiff = image.tiffRepresentation,
                       let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) {
                        try? png.write(to: URL(fileURLWithPath: path))
                    }
                }
                web.takeSnapshot(with: nil) { image, _ in
                    save(image, snap)
                    // second frame: scrolled to the bottom, so the whole page gets reviewed
                    self.web.evaluateJavaScript("window.scrollTo(0, document.body.scrollHeight);") { _, _ in
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
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

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    private func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Sovereign", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
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
}
