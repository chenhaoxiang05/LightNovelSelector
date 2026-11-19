import Darwin
import Foundation

struct SidecarConnectionError: LocalizedError {
    let detail: String
    var errorDescription: String? { detail }
}

private struct CoreRequestError: LocalizedError {
    let detail: String
    var errorDescription: String? { detail }
}

// JSONSerialization creates this object on the I/O queue. After handoff only the UI reads it.
private struct CoreReply: @unchecked Sendable {
    let value: [String: Any]
}

@MainActor
final class Sidecar {
    private let io = SidecarIO()
    private var nextID = 0

    func request(_ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
        nextID += 1
        let id = nextID
        let data = try JSONSerialization.data(withJSONObject: ["id": id, "method": method, "params": params])
        guard data.count < 1_048_576 else { throw CoreRequestError(detail: "请求过大，请缩短输入。") }
        let reply = try await io.exchange(data, id: id, method: method)
        return reply.value
    }

    func close() { io.close() }
}

// All Process and pipe state lives on this serial queue. Slow reads, startup and JSON
// decoding stay off the main actor and request/response pairs cannot interleave.
private final class SidecarIO: @unchecked Sendable {
    private let queue = DispatchQueue(label: "LightNovelSelector.Sidecar")
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?

    func exchange(_ data: Data, id: Int, method: String) async throws -> CoreReply {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    if self.process?.isRunning != true {
                        self.stop()
                        guard method == "ping" || method == "bootstrap" else {
                            throw SidecarConnectionError(detail: "分类核心已退出。请重新连接并扫描书库。")
                        }
                        try self.launch()
                    }
                    guard let input = self.input, let output = self.output else {
                        throw SidecarConnectionError(detail: "分类核心管道未连接。")
                    }
                    try input.write(contentsOf: data + [0x0a])
                    let bytes = try self.readLine(output, timeout: 180)
                    guard let envelope = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
                          envelope["id"] as? Int == id, let success = envelope["ok"] as? Bool else {
                        throw SidecarConnectionError(detail: "分类核心返回了无效的协议响应。")
                    }
                    if !success {
                        let error = envelope["error"] as? [String: Any]
                        throw CoreRequestError(detail: error?["message"] as? String ?? "分类请求失败。")
                    }
                    guard let result = envelope["result"] as? [String: Any] else {
                        throw SidecarConnectionError(detail: "分类核心返回了无法读取的结果。")
                    }
                    continuation.resume(returning: CoreReply(value: result))
                } catch let error as CoreRequestError {
                    continuation.resume(throwing: error)
                } catch {
                    self.stop()
                    let failure = error as? SidecarConnectionError
                        ?? SidecarConnectionError(detail: "分类核心通信失败：\(error.localizedDescription)")
                    continuation.resume(throwing: failure)
                }
            }
        }
    }

    func close() { queue.async { self.stop() } }

    private func stop() {
        // EOF lets a healthy server exit its protocol loop.
        try? input?.close()
        try? output?.close()
        if let process, process.isRunning { process.terminate() }
        input = nil
        output = nil
        process = nil
    }

    private func readLine(_ file: FileHandle, timeout: TimeInterval) throws -> Data {
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        var reply = Data()
        var buffer = [UInt8](repeating: 0, count: 65_536)
        var fd = pollfd(fd: file.fileDescriptor, events: Int16(POLLIN), revents: 0)
        while true {
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            guard remaining > 0 else { throw SidecarConnectionError(detail: "分类核心响应超时。") }
            let ready = Darwin.poll(&fd, 1, Int32(ceil(remaining * 1_000)))
            if ready < 0 && errno == EINTR { continue }
            guard ready > 0 else { throw SidecarConnectionError(detail: "等待分类核心响应超时或中断。") }
            let count = Darwin.read(fd.fd, &buffer, buffer.count)
            if count < 0 && errno == EINTR { continue }
            guard count > 0 else {
                throw SidecarConnectionError(detail: "分类核心已退出。请检查 Python 3.10 或更高版本及 defusedxml 依赖，并重新连接。")
            }
            let chunk = buffer.prefix(count)
            if let end = chunk.firstIndex(of: 0x0a) {
                reply.append(contentsOf: chunk[..<end])
                return reply
            }
            reply.append(contentsOf: chunk)
            guard reply.count <= 256 * 1_024 * 1_024 else {
                throw SidecarConnectionError(detail: "分类核心响应过大，请缩小所选目录后重试。")
            }
        }
    }

    private func launch() throws {
        let child = Process()
        let resources = Bundle.main.resourceURL
        let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/LightNovelSelector.Sidecar")
        if FileManager.default.isExecutableFile(atPath: helper.path) {
            child.executableURL = helper
        } else {
            guard let core = resources?.appendingPathComponent("core"),
                  FileManager.default.fileExists(atPath: core.appendingPathComponent("lightnovel_sidecar.py").path) else {
                throw SidecarConnectionError(detail: "未找到分类核心。请重新构建或安装完整的应用。")
            }
            child.executableURL = try pythonInterpreter(resources: resources)
            // -I drops user-site, inherited PYTHON* settings and the current working directory.
            // Only the explicitly bundled package is added to the import path.
            let bootstrap = """
                import runpy, sys
                sys.path.insert(0, sys.argv[1])
                runpy.run_module('lightnovel_sidecar', run_name='__main__')
                """
            child.arguments = ["-I", "-B", "-u", "-c", bootstrap, core.path]
            child.currentDirectoryURL = core
        }
        let toCore = Pipe()
        let fromCore = Pipe()
        child.standardInput = toCore
        child.standardOutput = fromCore
        child.standardError = FileHandle.standardError
        // A core crash between a liveness check and a write must not signal the GUI.
        _ = fcntl(toCore.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        try child.run()
        process = child
        input = toCore.fileHandleForWriting
        output = fromCore.fileHandleForReading
    }

    private func pythonInterpreter(resources: URL?) throws -> URL {
        let environment = ProcessInfo.processInfo.environment
        let override = environment["LN_SELECTOR_PYTHON"]
        var candidates: [String]
        if let override, !override.isEmpty {
            candidates = [override]
        } else {
            let configured = resources.flatMap { try? String(contentsOf: $0.appendingPathComponent("python-path"), encoding: .utf8) }
            candidates = [configured?.trimmingCharacters(in: .whitespacesAndNewlines)].compactMap { $0 }
            candidates += ["/opt/homebrew/bin/python3", "/usr/local/bin/python3",
                           "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"]
            candidates += (environment["PATH"] ?? "").split(separator: ":").filter { $0.hasPrefix("/") }.map { "\($0)/python3" }
            candidates.append("/usr/bin/python3")
        }
        var checked: Set<String> = []
        for path in candidates where path.hasPrefix("/") && checked.insert(path).inserted
            && FileManager.default.isExecutableFile(atPath: path) {
            let probe = Process()
            probe.executableURL = URL(fileURLWithPath: path)
            probe.arguments = ["-I", "-S", "-c", "import sys; sys.exit(sys.version_info < (3, 10))"]
            probe.standardOutput = FileHandle.nullDevice
            probe.standardError = FileHandle.nullDevice
            do {
                try probe.run()
                probe.waitUntilExit()
                if probe.terminationStatus == 0 { return URL(fileURLWithPath: path) }
            } catch { continue }
        }
        throw SidecarConnectionError(detail: "未找到 Python 3.10 或更高版本。请安装 Python，或将 LN_SELECTOR_PYTHON 指向可用解释器的绝对路径。")
    }
}
