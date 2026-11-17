import UIKit
import WebKit

@main
class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    func application(_ application: UIApplication, didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds)
        let navigation = UINavigationController(rootViewController: ScannerController())
        let appearance = UINavigationBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(red: 0, green: 0.553, blue: 0.616, alpha: 1)
        appearance.titleTextAttributes = [.foregroundColor: UIColor.white]
        navigation.navigationBar.standardAppearance = appearance
        navigation.navigationBar.scrollEdgeAppearance = appearance
        navigation.navigationBar.tintColor = .white
        window.rootViewController = navigation
        window.tintColor = UIColor(red: 0, green: 0.553, blue: 0.616, alpha: 1)
        window.makeKeyAndVisible()
        self.window = window
        return true
    }
}

final class ScannerController: UIViewController, WKNavigationDelegate, WKUIDelegate {
    private let defaults = UserDefaults.standard
    private var webView: WKWebView!
    private let progress = UIProgressView(progressViewStyle: .bar)
    private var observation: NSKeyValueObservation?
    private let notice = UILabel()
    private var server: URL!
    private var downloadTask: URLSessionDownloadTask?
    private var exportedFile: URL?
    private var isSharing = false
    private let defaultServer = "http://localhost:8787"

    override func viewDidLoad() {
        super.viewDidLoad()
        title = "TailScan"
        view.backgroundColor = .systemBackground
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.applicationNameForUserAgent = "TailScan-iOS/1.2"
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.isOpaque = false
        webView.backgroundColor = UIColor(red: 0.96, green: 0.97, blue: 0.94, alpha: 1)
        webView.allowsBackForwardNavigationGestures = true
        webView.translatesAutoresizingMaskIntoConstraints = false
        progress.translatesAutoresizingMaskIntoConstraints = false
        notice.translatesAutoresizingMaskIntoConstraints = false
        notice.numberOfLines = 0
        notice.textAlignment = .center
        notice.font = .preferredFont(forTextStyle: .body)
        notice.textColor = .secondaryLabel
        notice.isHidden = true
        view.addSubview(webView); view.addSubview(progress); view.addSubview(notice)
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            webView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            progress.topAnchor.constraint(equalTo: webView.topAnchor),
            progress.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            progress.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            notice.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            notice.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 28),
            notice.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -28)
        ])
        observation = webView.observe(\.estimatedProgress, options: [.new]) { [weak self] web, _ in
            self?.progress.progress = Float(web.estimatedProgress)
            self?.progress.isHidden = web.estimatedProgress >= 1
        }
        navigationItem.leftBarButtonItem = UIBarButtonItem(image: UIImage(systemName: "gearshape"), style: .plain, target: self, action: #selector(settings))
        navigationItem.rightBarButtonItem = UIBarButtonItem(image: UIImage(systemName: "arrow.clockwise"), style: .plain, target: self, action: #selector(reload))
        server = Self.validServer(defaults.string(forKey: "server") ?? defaultServer) ?? URL(string: defaultServer)!
        if defaults.string(forKey: "server") == nil {
            notice.isHidden = false; webView.isHidden = true
            notice.text = "Nhập địa chỉ máy chủ TailScan của bạn để bắt đầu."
            DispatchQueue.main.async { [weak self] in self?.settings() }
        } else { loadServer() }
        NotificationCenter.default.addObserver(self, selector: #selector(returnedToApp), name: UIApplication.willEnterForegroundNotification, object: nil)
    }

    /// Allow Tailscale DNS/IP and explicit private LAN addresses. No credentials or paths.
    static func validServer(_ text: String) -> URL? {
        guard var c = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(c.scheme?.lowercased() ?? ""), let host = c.host?.lowercased(),
              c.user == nil, c.password == nil, c.query == nil, c.fragment == nil,
              c.path.isEmpty || c.path == "/", c.port == nil || (1...65535).contains(c.port!) else { return nil }
        let parts = host.split(separator: ".").compactMap { Int($0) }
        let ipv4 = parts.count == 4 && parts.allSatisfy { (0...255).contains($0) }
        let privateIP = ipv4 && (parts[0] == 10 || parts[0] == 127 ||
            (parts[0] == 192 && parts[1] == 168) || (parts[0] == 172 && (16...31).contains(parts[1])) ||
            (parts[0] == 100 && (64...127).contains(parts[1])))
        guard host.hasSuffix(".ts.net") || host.hasSuffix(".local") || host == "localhost" || privateIP else { return nil }
        c.path = "/"; return c.url
    }

    private func loadServer() {
        notice.isHidden = true; webView.isHidden = false
        webView.load(URLRequest(url: server, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 25))
    }
    @objc private func reload() { if defaults.string(forKey: "server") == nil { settings() } else { loadServer() } }
    @objc private func returnedToApp() { if defaults.string(forKey: "server") != nil && !notice.isHidden { loadServer() } }
    @objc private func settings() {
        let sheet = UIAlertController(title: "Máy xử lý TailScan", message: "Bật Tailscale trên iPhone và giữ máy xử lý hoạt động. Ảnh và OCR được xử lý trên máy này.", preferredStyle: .alert)
        sheet.addTextField { field in
            field.text = self.defaults.string(forKey: "server") ?? ""
            field.placeholder = "http://your-server.your-tailnet.ts.net:8088"
            field.keyboardType = .URL; field.autocorrectionType = .no
            field.autocapitalizationType = .none; field.clearButtonMode = .whileEditing
        }
        sheet.addAction(UIAlertAction(title: "Hủy", style: .cancel))
        sheet.addAction(UIAlertAction(title: "Lưu và kết nối", style: .default) { [weak self, weak sheet] _ in
            guard let self = self else { return }
            guard let url = Self.validServer(sheet?.textFields?.first?.text ?? "") else {
                self.message("Địa chỉ chưa hợp lệ", "Nhập URL máy Tailscale (.ts.net hoặc IP 100.64–100.127) hay mạng nội bộ, gồm cổng nếu cần.")
                return
            }
            self.server = url; self.defaults.set(url.absoluteString, forKey: "server"); self.loadServer()
        })
        present(sheet, animated: true)
    }
    private func message(_ title: String, _ text: String) {
        guard presentedViewController == nil else { return }
        let alert = UIAlertController(title: title, message: text, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Đóng", style: .default)); present(alert, animated: true)
    }
    private func sameServer(_ url: URL) -> Bool {
        url.scheme == server.scheme && url.host == server.host && url.port == server.port
    }
    private func isExport(_ url: URL) -> Bool {
        guard sameServer(url) else { return false }
        let parts = url.path.split(separator: "/")
        return parts.count == 4 && parts[0] == "api" && ["jobs", "library"].contains(String(parts[1])) &&
            parts[2].count == 32 && parts[2].allSatisfy { $0.isHexDigit } &&
            ["document.pdf", "text.txt", "document.md"].contains(String(parts[3]))
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if isExport(url) { decisionHandler(.cancel); export(url); return }
        if sameServer(url) || url.absoluteString == "about:blank" { decisionHandler(.allow); return }
        decisionHandler(.cancel)
        if action.navigationType == .linkActivated, ["https", "http"].contains(url.scheme ?? "") {
            UIApplication.shared.open(url)
        }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, sameServer(url), !isExport(url) { webView.load(action.request) }
        return nil
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        guard (error as NSError).code != NSURLErrorCancelled else { return }
        progress.isHidden = true; webView.isHidden = true; notice.isHidden = false
        notice.text = "Chưa kết nối được máy xử lý.\n\nBật Tailscale, kiểm tra PC đang chạy TailScan, rồi bấm ↻. Có thể đổi máy chủ ở ⚙."
    }
    private func export(_ url: URL) {
        guard downloadTask == nil, !isSharing else { return }
        navigationItem.rightBarButtonItem?.isEnabled = false
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 60
        // Every redirect is checked, so an export cannot leave the selected server.
        let session = URLSession(configuration: config, delegate: ExportSessionDelegate(server: server), delegateQueue: nil)
        downloadTask = session.downloadTask(with: url) { [weak self] location, response, error in
            defer { session.finishTasksAndInvalidate() }
            guard let self = self else { return }
            var file: URL?; var problem: String?
            do {
                guard error == nil, let location = location, let response = response as? HTTPURLResponse,
                      response.statusCode == 200, response.url.map({ self.sameServer($0) }) == true else {
                    throw NSError(domain: "TailScan", code: 1)
                }
                let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let target = folder.appendingPathComponent(url.pathExtension == "pdf" ? "TailScan.pdf" : "TailScan.\(url.pathExtension)")
                try FileManager.default.moveItem(at: location, to: target); file = target
            } catch { problem = "Không tải được tài liệu. Kiểm tra kết nối Tailscale rồi thử lại." }
            DispatchQueue.main.async {
                self.downloadTask = nil; self.navigationItem.rightBarButtonItem?.isEnabled = true
                if let problem = problem { self.message("Không thể lưu", problem); return }
                guard let file = file else { return }
                self.exportedFile = file; self.isSharing = true
                let share = UIActivityViewController(activityItems: [file], applicationActivities: nil)
                share.popoverPresentationController?.barButtonItem = self.navigationItem.rightBarButtonItem
                share.completionWithItemsHandler = { [weak self] _, _, _, _ in
                    self?.isSharing = false; self?.exportedFile = nil
                    try? FileManager.default.removeItem(at: file.deletingLastPathComponent())
                }
                self.present(share, animated: true)
            }
        }
        downloadTask?.resume()
    }
}

private final class ExportSessionDelegate: NSObject, URLSessionTaskDelegate {
    let server: URL
    init(server: URL) { self.server = server }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        let url = request.url
        completionHandler(url?.scheme == server.scheme && url?.host == server.host && url?.port == server.port ? request : nil)
    }
}
