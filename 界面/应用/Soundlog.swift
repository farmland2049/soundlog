import Cocoa
import WebKit

func iconImage() -> NSImage {
    let image = NSImage(size: NSSize(width: 1024, height: 1024))
    image.lockFocus()
    NSColor(calibratedRed: 0.93, green: 0.95, blue: 0.90, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 32, y: 32, width: 960, height: 960), xRadius: 220, yRadius: 220).fill()
    NSColor(calibratedRed: 0.17, green: 0.34, blue: 0.26, alpha: 1).setStroke()
    let heights: [CGFloat] = [150, 280, 420, 560, 350, 220, 110]
    for (i, height) in heights.enumerated() {
        let path = NSBezierPath()
        path.lineWidth = 44; path.lineCapStyle = .round
        let x = CGFloat(278 + i * 78)
        path.move(to: NSPoint(x: x, y: 512 - height / 2))
        path.line(to: NSPoint(x: x, y: 512 + height / 2)); path.stroke()
    }
    image.unlockFocus()
    return image
}

if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--icon" {
    let image = iconImage()
    let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
    try rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
    exit(0)
}

final class Delegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.applicationIconImage = iconImage()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1200, height: 850), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Soundlog"; window.center(); window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 720, height: 540)
        web = WKWebView(frame: window.contentView!.bounds)
        web.autoresizingMask = [.width, .height]; web.navigationDelegate = self
        window.contentView!.addSubview(web)
        web.loadHTMLString("<html><body style='background:#f7f8f5;color:#45624c;font:18px -apple-system;padding:80px'>正在打开记录…</body></html>", baseURL: nil)
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        let root = Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        DispatchQueue.global().async {
            let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            process.arguments = [root.appendingPathComponent("scripts/launch_soundlog.py").path, "--no-open"]
            process.currentDirectoryURL = root
            let output = Pipe(); let errors = Pipe(); process.standardOutput = output; process.standardError = errors
            do {
                try process.run()
                let bytes = output.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit()
                guard process.terminationStatus == 0, let text = String(data: bytes, encoding: .utf8), let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)), url.host == "127.0.0.1" else { throw NSError(domain: "Soundlog", code: 1) }
                DispatchQueue.main.async { self.web.load(URLRequest(url: url)) }
            } catch {
                DispatchQueue.main.async {
                    let alert = NSAlert(); alert.messageText = "暂时无法打开 Soundlog"
                    alert.informativeText = "请重新打开应用。详细日志可在项目的调试目录查看。"; alert.runModal()
                }
            }
        }
        let menu = NSMenu(); let app = NSMenuItem(); menu.addItem(app)
        let submenu = NSMenu(); submenu.addItem(withTitle: "退出 Soundlog", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); app.submenu = submenu; NSApp.mainMenu = menu
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); return true
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        decisionHandler(url.host == "127.0.0.1" || url.scheme == "about" ? .allow : .cancel)
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = Delegate(); app.delegate = delegate; app.run()
