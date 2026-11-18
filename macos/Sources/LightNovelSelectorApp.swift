import AppKit
import SwiftUI

// The generic property wrapper also works with standalone Command Line Tools SDKs.
private typealias ViewState<Value> = SwiftUI.State<Value>

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = LibraryModel()
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if model.writesInProgress {
            model.notice = "文件操作仍在进行，请在完成后退出。"
            return .terminateCancel
        }
        return .terminateNow
    }
    func applicationWillTerminate(_ notification: Notification) { model.core.close() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct LightNovelSelectorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    var body: some Scene {
        Window("轻小说整理", id: "library") {
            Workspace(model: delegate.model)
                .windowDismissBehavior(delegate.model.writesInProgress ? .disabled : .automatic)
        }
        .defaultSize(width: 1030, height: 690)
        .windowResizability(.contentMinSize)
    }
}

private enum Page: String, CaseIterable, Identifiable {
    case library = "整理工作台", history = "整理历史", settings = "识别设置"
    var id: Self { self }
    var icon: String {
        switch self {
        case .library: "books.vertical"
        case .history: "clock.arrow.circlepath"
        case .settings: "slider.horizontal.3"
        }
    }
}

private struct EditSelection: Identifiable {
    let file: PreviewFile
    let revision: Int
    var id: Int { file.id }
}

private struct Workspace: View {
    @Bindable var model: LibraryModel
    @ViewState private var page: Page? = .library
    @ViewState private var query = ""
    @ViewState private var filter = StatusFilter.all
    @ViewState private var selection: Int?
    @ViewState private var editing: EditSelection?
    @ViewState private var viewing: Batch?
    @ViewState private var confirmingApply = false
    @ViewState private var pendingUndo: Batch?

    private var selected: PreviewFile? {
        guard let selection, model.plans.indices.contains(selection) else { return nil }
        return model.plans[selection]
    }
    private var visibleRows: [PreviewFile] {
        model.plans.filter { file in
            filter.includes(file) && (query.isEmpty || file.name.localizedCaseInsensitiveContains(query)
                                       || file.series.localizedCaseInsensitiveContains(query))
        }
    }

    var body: some View {
        NavigationSplitView {
            List(Page.allCases, selection: $page) { item in
                Label(item.rawValue, systemImage: item.icon).tag(item)
            }
            .navigationSplitViewColumnWidth(min: 155, ideal: 178, max: 220)
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 5) {
                    Label("当前目录", systemImage: "folder").font(.caption).foregroundStyle(.secondary)
                    Text(model.folder.isEmpty ? "尚未选择" : URL(fileURLWithPath: model.folder).lastPathComponent)
                        .font(.callout.weight(.medium)).lineLimit(1).help(model.folder)
                }.frame(maxWidth: .infinity, alignment: .leading).padding()
            }
        } detail: {
            VStack(alignment: .leading, spacing: 0) {
                switch page ?? .library {
                case .library: library
                case .history: history
                case .settings: settings
                }
                Divider()
                HStack(spacing: 10) {
                    if model.operation.running { ProgressView().controlSize(.small) }
                    Text(model.operation.message).lineLimit(2).textSelection(.enabled)
                    Spacer()
                    if !model.connected && !model.sending {
                        Button("重新连接") { Task { await model.connect() } }
                    } else if model.operation.canCancel {
                        Button("取消扫描") { Task { await model.command("cancel_operation") } }
                            .disabled(model.sending)
                    }
                }
                .font(.callout).padding(.horizontal, 18).padding(.vertical, 9)
            }
            .navigationTitle((page ?? .library).rawValue)
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button("选择目录", systemImage: "folder.badge.plus", action: chooseFolder)
                        .keyboardShortcut("o").disabled(!model.idle)
                }
                if page == .library && !model.folder.isEmpty {
                    ToolbarItem(placement: .primaryAction) {
                        Button("扫描预览", systemImage: "arrow.clockwise") {
                            Task { await model.command("start_scan") }
                        }.keyboardShortcut("r").disabled(!model.idle)
                    }
                }
            }
        }
        .frame(minWidth: 740, minHeight: 500)
        .task { await model.connect() }
        .task(id: "\(page?.rawValue ?? "")|\(model.folder)") {
            if page == .history { await model.reloadHistory() }
        }
        .onChange(of: model.revision) { _, _ in selection = nil }
        .onChange(of: query) { _, _ in selection = nil }
        .onChange(of: filter) { _, _ in selection = nil }
        .sheet(item: $editing) { EditFileView(model: model, item: $0) }
        .sheet(item: $viewing) { ReportView(model: model, batch: $0) }
        .alert("确认整理整个预览？", isPresented: $confirmingApply) {
            Button("取消", role: .cancel) {}
            Button("移动 \(model.movableCount) 个文件") { Task { await model.command("start_apply") } }
        } message: {
            Text("目录：\(model.folder)\n完整预览共 \(model.plans.count) 项。搜索和筛选只影响显示范围。")
        }
        .alert("撤销这次整理？", isPresented: Binding(get: { pendingUndo != nil },
                    set: { if !$0 { pendingUndo = nil } }), presenting: pendingUndo) { batch in
            Button("取消", role: .cancel) {}
            Button("恢复原位置", role: .destructive) {
                Task { await model.command("start_undo", ["report_id": batch.id]) }
            }
        } message: { batch in
            Text("核心将核对文件状态，再恢复这个批次中移动的 \(batch.moved) 个文件。")
        }
        .alert("轻小说整理", isPresented: Binding(get: { model.notice != nil },
                set: { if !$0 { model.notice = nil } })) {
            Button("好") { model.notice = nil }
        } message: { Text(model.notice ?? "") }
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "选择目录"
        if !model.folder.isEmpty { panel.directoryURL = URL(fileURLWithPath: model.folder) }
        if panel.runModal() == .OK, let url = panel.url {
            page = .library
            Task { await model.command("set_folder", ["path": url.path]) }
        }
    }

    @ViewBuilder private var library: some View {
        if model.plans.isEmpty {
            ZStack {
                RadialGradient(colors: [Color.accentColor.opacity(0.11), .clear],
                               center: .center, startRadius: 10, endRadius: 340)
                    .accessibilityHidden(true)
                VStack(spacing: 14) {
                    Image(systemName: "books.vertical.fill").font(.system(size: 45, weight: .medium))
                        .symbolRenderingMode(.hierarchical).foregroundStyle(.tint)
                        .accessibilityHidden(true)
                    Text(model.folder.isEmpty ? "选择你的轻小说目录" : "预览分类结果")
                        .font(.system(size: 25, weight: .semibold))
                    Text(model.folder.isEmpty ? "先核对每个文件的系列和目标位置，确认后再整理。"
                         : URL(fileURLWithPath: model.folder).path)
                        .foregroundStyle(.secondary).textSelection(.enabled)
                    Button {
                        if model.folder.isEmpty { chooseFolder() }
                        else { Task { await model.command("start_scan") } }
                    } label: {
                        Label(model.folder.isEmpty ? "选择目录" : "扫描并预览",
                              systemImage: model.folder.isEmpty ? "folder" : "magnifyingglass")
                    }.buttonStyle(.glassProminent).controlSize(.large).disabled(!model.idle)
                }.padding(28).multilineTextAlignment(.center)
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    TextField("搜索文件或系列", text: $query).textFieldStyle(.roundedBorder)
                        .accessibilityLabel("搜索文件或系列")
                    Picker("状态", selection: $filter) {
                        ForEach(StatusFilter.allCases) { Text($0.rawValue).tag($0) }
                    }.frame(maxWidth: 175)
                }
                Table(visibleRows, selection: $selection) {
                    TableColumn("文件名", value: \.name).width(min: 130, ideal: 230)
                    TableColumn("系列", value: \.series).width(min: 85, ideal: 145)
                    TableColumn("置信度", value: \.confidence).width(58)
                    TableColumn("状态", value: \.status).width(62)
                }.contextMenu(forSelectionType: Int.self) { ids in
                    if let id = ids.first, let file = model.plans.first(where: { $0.id == id }) {
                        Button("查看与修正…") { edit(file) }
                    }
                } primaryAction: { ids in
                    if let id = ids.first, let file = model.plans.first(where: { $0.id == id }) { edit(file) }
                }
                HStack {
                    VStack(alignment: .leading) {
                        Text("显示 \(visibleRows.count) / \(model.plans.count) 项")
                        Text("共 \(model.movableCount) 项待移动").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    GlassEffectContainer(spacing: 12) {
                        HStack(spacing: 10) {
                            Button("查看与修正…") { if let selected { edit(selected) } }
                                .buttonStyle(.glass).disabled(selected == nil || !model.idle)
                            Button("确认整理…") { confirmingApply = true }
                                .buttonStyle(.glassProminent).keyboardShortcut(.return, modifiers: .command)
                                .disabled(!model.idle || model.movableCount == 0)
                        }
                    }
                }
            }.padding(16)
        }
    }

    private func edit(_ file: PreviewFile) {
        guard model.idle else { return }
        editing = EditSelection(file: file, revision: model.revision)
    }

    @ViewBuilder private var history: some View {
        if model.history.isEmpty {
            ContentUnavailableView("暂无整理记录", systemImage: "clock.arrow.circlepath",
                                   description: Text(model.folder.isEmpty ? "选择目录后即可查看整理记录。" : "完成整理后，可以在这里查看报告并撤销。"))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            List(model.history) { batch in
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(batch.date).font(.headline)
                        Text("\(batch.status) · 移动 \(batch.moved) · 跳过 \(batch.skipped) · 异常 \(batch.errors)")
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("查看报告") { viewing = batch }.disabled(!model.idle)
                    Button("撤销…") { pendingUndo = batch }.disabled(!batch.canUndo || !model.idle)
                }.padding(.vertical, 5)
            }
        }
    }

    private var settings: some View {
        Form {
            Section("扫描选项") {
                toggle("包含子目录", key: "recursive", description: "同时扫描所选目录下的子文件夹。")
                toggle("联网补充元数据", key: "use_network", description: "使用文件名中的标题或系列查询已启用的在线书库。")
                toggle("自动重命名", key: "auto_rename", description: "生成预览时为支持的条目规划新文件名。")
            }
            Text("更改会立即保存。已有预览需要重新扫描。").font(.callout).foregroundStyle(.secondary)
        }.formStyle(.grouped).disabled(!model.idle)
    }

    private func toggle(_ title: String, key: String, description: String) -> some View {
        Toggle(isOn: Binding(get: { model.settings[key] as? Bool ?? false },
                            set: { value in Task { await model.updateSetting(key, value: value) } })) {
            Text(title)
            Text(description).foregroundStyle(.secondary)
        }
    }
}

private enum StatusFilter: String, CaseIterable, Identifiable {
    case all = "全部", ready = "待移动", duplicates = "重复", errors = "异常"
    var id: Self { self }
    func includes(_ file: PreviewFile) -> Bool {
        switch self {
        case .all: true
        case .ready: file.willMove
        case .duplicates: file.statusKey == "duplicate"
        case .errors: file.statusKey == "error"
        }
    }
}

private struct EditFileView: View {
    let model: LibraryModel
    let item: EditSelection
    @Environment(\.dismiss) private var dismiss
    @ViewState private var series: String
    @ViewState private var applyGroup = false
    @ViewState private var confirmGroup = false
    init(model: LibraryModel, item: EditSelection) {
        self.model = model
        self.item = item
        _series = State(initialValue: item.file.series)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(item.file.name).font(.title2.bold()).textSelection(.enabled)
            ScrollView {
                Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 9) {
                    detail("原位置", item.file.source)
                    detail("目标位置", item.file.target)
                    detail("识别信息", [item.file.authors, item.file.volume, item.file.language].joined(separator: " · "))
                    detail("分类依据", ([item.file.reason] + item.file.evidence + [item.file.note])
                        .filter { !$0.isEmpty }.joined(separator: "\n"))
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            Divider()
            TextField("系列名称", text: $series)
            Toggle("同时修正预览中原属这个系列的文件", isOn: $applyGroup)
            HStack {
                Spacer()
                Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("保存修正") {
                    if applyGroup { confirmGroup = true } else { save() }
                }.keyboardShortcut(.defaultAction).buttonStyle(.glassProminent)
                    .disabled(!model.idle || item.file.statusKey == "moved" || series.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }.padding(24).frame(width: 535, height: 400)
        .alert("修正同系列的全部条目？", isPresented: $confirmGroup) {
            Button("取消", role: .cancel) {}
            Button("更新预览") { save() }
        } message: { Text("将「\(item.file.series)」组中的条目修正为「\(series)」。") }
    }

    private func detail(_ key: String, _ value: String) -> some View {
        GridRow {
            Text(key).foregroundStyle(.secondary).gridColumnAlignment(.trailing)
            Text(value).textSelection(.enabled)
        }
    }
    private func save() {
        let args: Payload = ["index": item.file.id, "series_name": series, "plans_revision": item.revision,
                             "scope": applyGroup ? "same_series" : "single"]
        Task {
            await model.command("edit_plans", args)
            if model.revision != item.revision || model.notice != nil { dismiss() }
        }
    }
}

private struct ReportView: View {
    let model: LibraryModel
    let batch: Batch
    @Environment(\.dismiss) private var dismiss
    @ViewState private var report: Payload?
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("整理报告").font(.title2.bold())
            Text("\(batch.date) · 移动 \(batch.moved) · 跳过 \(batch.skipped)").foregroundStyle(.secondary)
            if let report {
                let items = report["items"] as? [Payload] ?? []
                List(items.indices, id: \.self) { i in
                    VStack(alignment: .leading) {
                        Text(items[i]["source_path"] as? String ?? "").textSelection(.enabled)
                        Text(items[i]["actual_target_path"] as? String ?? items[i]["target_path"] as? String ?? "")
                            .foregroundStyle(.secondary).textSelection(.enabled)
                    }
                }
                if report["items_truncated"] as? Bool == true {
                    Text("显示前 \(items.count) 条，共 \(report["item_count"] as? Int ?? items.count) 条。")
                }
            } else { ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity) }
            HStack { Spacer(); Button("完成") { dismiss() }.keyboardShortcut(.defaultAction) }
        }.padding(24).frame(width: 560, height: 400)
        .task { report = await model.report(batch.id); if report == nil { dismiss() } }
    }
}
