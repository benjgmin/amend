import SwiftUI

struct AirportDetailView: View {
    let id: String
    @Environment(AirportStore.self) private var store

    enum Tab: String, CaseIterable { case latest = "THIS CYCLE", history = "HISTORY" }
    @State private var tab: Tab = .latest

    var body: some View {
        VStack(spacing: 0) {
            header
            tabBar
            switch tab {
            case .latest: LatestView(id: id)
            case .history: HistoryView(id: id)
            }
        }
        .background(EFB.bg)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(EFB.bg, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .principal) {
                Text(id).font(EFB.mono(15, .bold)).tracking(2).foregroundStyle(EFB.text)
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    store.setHome(store.home == id ? nil : id)
                } label: {
                    Image(systemName: store.home == id ? "house.fill" : "house")
                }
                .accessibilityLabel(store.home == id ? "Unset home airport" : "Set as home airport")
            }
        }
    }

    private var header: some View {
        let info = store.info(for: id)
        return VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(id).font(EFB.mono(30, .bold)).foregroundStyle(EFB.text)
                if let icao = info?.icao, icao != id {
                    Text(icao).font(EFB.mono(14)).foregroundStyle(EFB.faint)
                }
                Spacer()
                if store.index != nil {
                    CountAnnunciators(counts: store.counts(for: id))
                }
            }
            if let info {
                Text(info.name).font(.headline).foregroundStyle(EFB.text)
                if !info.location.isEmpty {
                    Text(info.location.uppercased()).font(EFB.mono(11)).foregroundStyle(EFB.dim)
                }
            }
        }
        .efbPanel()
        .padding(.horizontal)
        .padding(.top, 8)
    }

    private var tabBar: some View {
        HStack(spacing: 0) {
            ForEach(Tab.allCases, id: \.self) { t in
                Button { tab = t } label: {
                    VStack(spacing: 6) {
                        Text(t.rawValue)
                            .font(EFB.mono(12, .bold))
                            .tracking(1.5)
                            .foregroundStyle(tab == t ? EFB.cyan : EFB.dim)
                        Rectangle()
                            .fill(tab == t ? EFB.cyan : Color.clear)
                            .frame(height: 2)
                    }
                    .frame(maxWidth: .infinity)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal)
        .padding(.top, 12)
        .overlay(alignment: .bottom) { Rectangle().fill(EFB.line).frame(height: 1) }
    }
}

// MARK: - This cycle

private struct LatestView: View {
    let id: String
    @Environment(AirportStore.self) private var store
    @State private var data: AirportChanges?
    @State private var loaded = false
    @State private var error: String?

    var body: some View {
        List {
            if let data {
                Text("\(Cycle.efb(data.fromCycle))  →  \(Cycle.efb(data.toCycle))")
                    .font(EFB.mono(11))
                    .foregroundStyle(EFB.dim)
                    .efbRow(top: 12, bottom: 4)
                ChangeSections(changes: data.changes)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .overlay {
            if let error {
                ContentUnavailableView("Couldn't load", systemImage: "wifi.exclamationmark",
                                       description: Text(error))
            } else if loaded && data == nil {
                NoChangesView(text: store.meta.map {
                    "NOTHING CHANGED AT \(id)\n\(Cycle.efb($0.fromCycle)) → \(Cycle.efb($0.toCycle))"
                } ?? "NOTHING CHANGED AT \(id) THIS CYCLE")
            } else if !loaded {
                ProgressView()
            }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        do {
            data = try await API.latest(id)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        loaded = true
    }
}

// MARK: - History

private struct HistoryView: View {
    let id: String

    @State private var history: AirportHistory?
    @State private var loaded = false
    @State private var error: String?
    @AppStorage(SettingsKey.historyRange) private var since: HistoryRange = .all
    @AppStorage(SettingsKey.historyShowFYI) private var showFYI = false

    private var groups: [(cycle: String, changes: [Change])] {
        guard let history else { return [] }
        let cutoff = since.months.flatMap { months in
            Calendar.current.date(byAdding: .month, value: -months, to: .now).map { Cycle.string($0) }
        }
        let entries = history.entries.filter { e in
            guard let c = e.cycle else { return false }
            if let cutoff, c < cutoff { return false }
            return showFYI || e.level != .fyi
        }
        let byCycle = Dictionary(grouping: entries) { $0.cycle ?? "" }
        return byCycle.keys.sorted(by: >).map { ($0, byCycle[$0] ?? []) }
    }

    var body: some View {
        List {
            controls.efbRow(top: 12, bottom: 8)
            ForEach(groups, id: \.cycle) { group in
                Section {
                    ForEach(group.changes) { ChangeRow(change: $0).efbRow(top: 3, bottom: 3) }
                } header: {
                    HStack(spacing: 8) {
                        Circle().fill(EFB.cyan).frame(width: 7, height: 7)
                        EFBHeader(text: "EFF \(Cycle.efb(group.cycle))", color: EFB.text)
                        Rectangle().fill(EFB.line).frame(height: 1)
                    }
                    .padding(.vertical, 4)
                }
                .listSectionSeparator(.hidden)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .overlay {
            if let error {
                ContentUnavailableView("Couldn't load", systemImage: "wifi.exclamationmark",
                                       description: Text(error))
            } else if loaded && history == nil {
                NoChangesView(text: "NO CHANGES RECORDED AT \(id)\nSINCE 08 AUG 2024")
            } else if loaded && groups.isEmpty {
                NoChangesView(text: "NOTHING IN THIS RANGE\nTRY A LONGER RANGE OR SHOW FYI",
                              color: EFB.dim).padding(.top, 60)
            } else if !loaded {
                ProgressView()
            }
        }
        .task {
            do { history = try await API.history(id) } catch { self.error = error.localizedDescription }
            loaded = true
        }
    }

    private var controls: some View {
        HStack(spacing: 6) {
            ForEach(HistoryRange.allCases) { s in
                Button { since = s } label: {
                    Text(s.rawValue)
                        .font(EFB.mono(12, .bold))
                        .frame(minWidth: 36)
                        .padding(.vertical, 6)
                        .foregroundStyle(since == s ? EFB.bg : EFB.dim)
                        .background(since == s ? EFB.cyan : EFB.panel, in: RoundedRectangle(cornerRadius: 5))
                }
                .buttonStyle(.plain)
            }
            Spacer()
            Button { showFYI.toggle() } label: {
                Annunciator(text: showFYI ? "FYI ON" : "FYI OFF", color: showFYI ? EFB.text : EFB.faint)
            }
            .buttonStyle(.plain)
        }
    }
}

// MARK: - Shared

struct ChangeSections: View {
    let changes: [Change]

    var body: some View {
        ForEach(Priority.allCases) { level in
            let group = changes.filter { $0.level == level }
            if !group.isEmpty {
                Section {
                    ForEach(group) { ChangeRow(change: $0).efbRow(top: 3, bottom: 3) }
                } header: {
                    HStack(spacing: 8) {
                        EFBHeader(text: "\(level.title)  \(group.count)", color: level.color)
                        Rectangle().fill(level.color.opacity(0.3)).frame(height: 1)
                    }
                    .padding(.vertical, 4)
                }
                .listSectionSeparator(.hidden)
            }
        }
    }
}

private struct NoChangesView: View {
    let text: String
    var color: Color = EFB.green

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "checkmark.circle").font(.system(size: 34)).foregroundStyle(color)
            Text(text)
                .font(EFB.mono(12, .semibold))
                .multilineTextAlignment(.center)
                .foregroundStyle(color)
        }
    }
}
