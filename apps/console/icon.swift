// Renders the app icon set: a graphite rounded square with a gold crown.
// Usage: swift icon.swift <out.iconset>   (then: iconutil -c icns <out.iconset>)
import Cocoa

let outDir = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.iconset"
try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

func render(_ px: Int) -> NSImage {
    let size = NSSize(width: px, height: px)
    let img = NSImage(size: size)
    img.lockFocus()
    let inset = CGFloat(px) * 0.08
    let rect = NSRect(x: inset, y: inset, width: CGFloat(px) - inset * 2, height: CGFloat(px) - inset * 2)
    let path = NSBezierPath(roundedRect: rect, xRadius: CGFloat(px) * 0.2, yRadius: CGFloat(px) * 0.2)
    let grad = NSGradient(starting: NSColor(calibratedRed: 0.16, green: 0.18, blue: 0.22, alpha: 1),
                          ending: NSColor(calibratedRed: 0.07, green: 0.08, blue: 0.10, alpha: 1))!
    grad.draw(in: path, angle: -90)
    let cfg = NSImage.SymbolConfiguration(pointSize: CGFloat(px) * 0.5, weight: .semibold)
    if let sym = NSImage(systemSymbolName: "crown.fill", accessibilityDescription: nil)?.withSymbolConfiguration(cfg) {
        let gold = NSColor(calibratedRed: 0.79, green: 0.64, blue: 0.15, alpha: 1)
        let tinted = NSImage(size: sym.size)
        tinted.lockFocus()
        sym.draw(in: NSRect(origin: .zero, size: sym.size))
        gold.set()
        NSRect(origin: .zero, size: sym.size).fill(using: .sourceAtop)
        tinted.unlockFocus()
        let s = sym.size
        let origin = NSPoint(x: (CGFloat(px) - s.width) / 2, y: (CGFloat(px) - s.height) / 2 + CGFloat(px) * 0.02)
        tinted.draw(in: NSRect(origin: origin, size: s))
    }
    img.unlockFocus()
    return img
}

func save(_ img: NSImage, _ name: String, _ px: Int) {
    guard let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) else { return }
    rep.size = NSSize(width: px, height: px)
    guard let png = rep.representation(using: .png, properties: [:]) else { return }
    try? png.write(to: URL(fileURLWithPath: "\(outDir)/\(name)"))
}

for base in [16, 32, 128, 256, 512] {
    save(render(base), "icon_\(base)x\(base).png", base)
    save(render(base * 2), "icon_\(base)x\(base)@2x.png", base * 2)
}
print("icon set written to \(outDir)")
