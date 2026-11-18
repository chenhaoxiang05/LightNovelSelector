import Foundation
import Observation

typealias Payload = [String: Any]

private extension Dictionary where Key == String, Value == Any {
    func string(_ key: String) -> String { self[key] as? String ?? "" }
    func count(_ key: String) -> Int { self[key] as? Int ?? 0 }
}

struct PreviewFile: Identifiable {
    let id: Int
    let name, series, source, target, status, statusKey, confidence, reason, note: String
    let authors, language, volume: String
    let willMove: Bool
    let evidence: [String]

    init(_ item: Payload) {
        id = item.count("index")
        name = item.string("file_name")
        series = item.string("series_name")
        source = item.string("source_path")
        target = item.string("target_path")
        status = item.string("status_label")
        statusKey = item.string("status")
        confidence = item.string("confidence_label")
        reason = item.string("classification_reason")
        note = item.string("note")
        authors = item.string("authors_label")
        language = item.string("language_label")
        volume = item.string("volume_label")
        willMove = item["will_move"] as? Bool ?? false
        evidence = item["classification_evidence"] as? [String] ?? []
    }
}

struct Batch: Identifiable {
    let id, date, status: String
    let moved, skipped, errors: Int
    let canUndo: Bool
    init(_ item: Payload) {
        id = item.string("report_id")
        date = item.string("created_at")
        status = item.string("status_label")
        let counts = item["summary"] as? Payload ?? [:]
        moved = counts.count("moved")
        skipped = counts.count("skipped")
        errors = counts.count("errors")
        canUndo = item["can_undo"] as? Bool ?? false
    }
}

struct Operation {
    var kind = "idle", state = "idle", message = "正在连接分类核心…"
    var done = 0, total = 0, canCancel = false
    var running: Bool { state == "running" }

    init() {}
    init(_ item: Payload) {
        kind = item.string("kind")
        state = item.string("state")
        message = item["error"] as? String ?? item.string("message")
        done = item.count("done")
        total = item.count("total")
        canCancel = item["can_cancel"] as? Bool ?? false
    }
}

@MainActor @Observable
final class LibraryModel {
    let core = Sidecar()
    var connected = false
    var sending = false
    var folder = ""
    var revision = -1
    var plans: [PreviewFile] = []
    var history: [Batch] = []
    var settings: Payload = [:]
    var operation = Operation()
    var notice: String?
    private var cursor = 0
    private var pollTask: Task<Void, Never>?
    // Core refuses concurrent mutations; also guard the gap before its first acknowledgement.
    private var writeRequested = false
    var writesInProgress: Bool {
        writeRequested || (operation.running && ["apply", "undo"].contains(operation.kind))
    }
    var idle: Bool { connected && !sending && !operation.running }
    var movableCount = 0
    var settingsNetwork: Bool { settings["use_network"] as? Bool ?? true }

    func connect() async {
        guard !sending, !connected else { return }
        sending = true
        defer { sending = false }
        do {
            let reply = try await core.request("ping")
            guard reply["protocol_version"] as? Int == 1 else {
                throw NSError(domain: "LightNovelSelector", code: 1,
                              userInfo: [NSLocalizedDescriptionKey: "分类核心协议版本不兼容。"])
            }
            receive(try await core.request("bootstrap"))
            connected = true
        } catch {
            disconnect(error)
        }
    }

    private func disconnect(_ error: Error) {
        pollTask?.cancel()
        pollTask = nil
        core.close()
        connected = false
        plans = []
        history = []
        movableCount = 0
        cursor = 0
        revision = -1
        operation = Operation()
        operation.message = "分类核心未连接"
        notice = error.localizedDescription
    }

    private func handle(_ error: Error) {
        if error is SidecarConnectionError { disconnect(error) }
        else { notice = error.localizedDescription }
    }

    private func receive(_ snapshot: Payload) {
        folder = snapshot.string("folder")
        settings = snapshot["settings"] as? Payload ?? [:]
        if let rows = snapshot["plans"] as? [Payload] {
            plans = rows.map(PreviewFile.init)
            movableCount = plans.lazy.filter(\.willMove).count
        }
        revision = snapshot.count("plans_revision")
        cursor = snapshot.count("log_cursor")
        operation = Operation(snapshot["operation"] as? Payload ?? [:])
    }

    func command(_ method: String, _ params: Payload = [:]) async {
        guard connected, !sending, (!operation.running || method == "cancel_operation") else { return }
        sending = true
        writeRequested = method == "start_apply" || method == "start_undo"
        defer { sending = false; writeRequested = false }
        do {
            let result = try await core.request(method, params)
            receive(result["snapshot"] as? Payload ?? result["state"] as? Payload ?? result)
            if let warning = result["warning"] as? String { notice = warning }
            if method == "set_folder" { history = [] }
            if operation.running { monitor() }
            else if method == "start_apply" || method == "start_undo" { await reloadHistory() }
        } catch { handle(error) }
    }

    private func monitor() {
        guard pollTask == nil else { return }
        pollTask = Task {
            defer { pollTask = nil }
            while !Task.isCancelled && operation.running {
                try? await Task.sleep(for: .milliseconds(300))
                if Task.isCancelled { return }
                if sending { continue }
                do {
                    let snapshot = try await core.request("poll", ["plans_revision": revision, "log_cursor": cursor])
                    receive(snapshot)
                } catch {
                    handle(error)
                    return
                }
            }
            if connected && !Task.isCancelled && ["apply", "undo"].contains(operation.kind) {
                await reloadHistory()
            }
        }
    }

    func updateSetting(_ key: String, value: Bool) async {
        var updated = settings
        updated[key] = value
        await command("save_settings", ["settings": updated])
    }

    func reloadHistory() async {
        guard connected, !folder.isEmpty, !operation.running else { return }
        let requestedFolder = folder
        do {
            let result = try await core.request("get_report_history")
            guard folder == requestedFolder else { return }
            history = (result["reports"] as? [Payload] ?? []).map(Batch.init)
            if let warning = result["warning"] as? String { notice = warning }
        } catch { handle(error) }
    }

    func report(_ id: String) async -> Payload? {
        guard idle else { return nil }
        do { return try await core.request("get_report", ["report_id": id]) }
        catch { handle(error); return nil }
    }
}
