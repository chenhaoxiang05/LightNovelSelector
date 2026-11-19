import Foundation

@main
struct WorkflowTest {
    struct Failed: LocalizedError {
        let errorDescription: String?
        init(_ reason: String) { errorDescription = reason }
    }

    @MainActor
    static func settle(_ model: LibraryModel) async throws {
        let end = ContinuousClock.now.advanced(by: .seconds(15))
        while model.operation.running && ContinuousClock.now < end {
            try await Task.sleep(for: .milliseconds(100))
        }
        guard !model.operation.running, model.operation.state != "error", model.notice == nil else {
            throw Failed(model.notice ?? model.operation.message)
        }
    }

    @MainActor
    static func main() async throws {
        guard CommandLine.arguments.count == 2 else { throw Failed("Pass a temporary test directory") }
        let folder = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let source = folder.appendingPathComponent("星之旅 第1卷.txt")
        let content = Data("Synthetic offline book".utf8)
        try content.write(to: source, options: .withoutOverwriting)
        let model = LibraryModel()
        defer { model.core.close() }
        await model.connect()
        guard model.connected else { throw Failed(model.notice ?? "Core unavailable") }
        await model.command("set_folder", ["path": folder.path])
        await model.updateSetting("use_network", value: false)
        guard !model.settingsNetwork else { throw Failed("Could not switch to offline mode") }
        await model.command("start_scan")
        try await settle(model)
        guard model.plans.count == 1, model.movableCount == 1,
              try Data(contentsOf: source) == content else { throw Failed("Preview changed the source or missed it") }
        let preview = model.plans[0]
        model.query = "TXT"
        model.statusFilter = .duplicates
        guard model.visibleRows.isEmpty else { throw Failed("Status filter did not hide a ready item") }
        model.statusFilter = .ready
        guard model.visibleRows.map(\.id) == [preview.id] else { throw Failed("Filename search failed") }
        model.query = "测试系列"
        guard model.visibleRows.isEmpty else { throw Failed("Unexpected match before editing") }
        await model.command("edit_plans", ["index": preview.id, "series_name": "测试系列",
                                           "scope": "single", "plans_revision": model.revision])
        guard model.visibleRows.first?.series == "测试系列", let target = model.plans.first?.target else {
            throw Failed(model.notice ?? "Manual correction failed")
        }
        await model.command("start_apply")
        try await settle(model)
        guard !FileManager.default.fileExists(atPath: source.path),
              try Data(contentsOf: URL(fileURLWithPath: target)) == content else { throw Failed("Move failed") }
        guard model.visibleRows.isEmpty else { throw Failed("Moved item remained in ready filter") }
        model.query = ""
        model.statusFilter = .all
        guard model.visibleRows.map(\.id) == [preview.id] else { throw Failed("Clearing filters lost a row") }
        await model.reloadHistory()
        guard let batch = model.history.first, batch.canUndo, batch.moved == 1,
              let report = await model.report(batch.id), report["item_count"] as? Int == 1 else {
            throw Failed("Expected one reversible history entry")
        }
        await model.command("start_undo", ["report_id": batch.id])
        try await settle(model)
        guard try Data(contentsOf: source) == content, !FileManager.default.fileExists(atPath: target) else {
            throw Failed("Undo failed")
        }
        guard model.visibleRows.isEmpty else { throw Failed("Preview remained visible after undo") }
        print("macOS: connected, previewed offline, filtered, corrected, moved, read history and restored original bytes")
    }
}
