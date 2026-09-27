import SwiftUI

struct AirportDetailView: View {
    let id: String
    @Environment(AirportStore.self) private var store

    enum Tab: String, CaseIterable { case latest = "This cycle", history = "History" }
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
                    Text(info.location).font(.subheadline).foregroundStyle(EFB.dim)
                }
            }
        }
        .efbPanel()
        .padding(.horizontal)
        .padding(.top, 8)
    }

    /// "UPCOMING" while the newest cycle isn't in effect yet, "LATEST" once it is
    private func label(for t: Tab) -> String {
        guard t == .latest, let meta = store.meta else { return t.rawValue }
        return Cycle.isInEffect(meta.toCycle) ? "Latest" : "Upcoming"
    }

    private var tabBar: some View {
        HStack(spacing: 0) {
            ForEach(Tab.allCases, id: \.self) { t in
                Button { tab = t } label: {
                    VStack(spacing: 6) {
                        Text(label(for: t))
                            .font(.system(size: 14, weight: .semibold))
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
                EffectiveNote(fromCycle: data.fromCycle, toCycle: data.toCycle)
                    .efbRow(top: 12, bottom: 6)
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
                NoChangesView(text: noChangesText)
            } else if !loaded {
                ProgressView()
            }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    /// talk about the new cycle, not the date range (things did change on the older date)
    private var noChangesText: String {
        guard let meta = store.meta else { return "NO CHANGES AT \(id) THIS CYCLE" }
        let eff = Cycle.efb(meta.toCycle)
        return Cycle.isInEffect(meta.toCycle)
            ? "NOTHING CHANGED AT \(id)\nIN THE \(eff) CYCLE"
            : "NO UPCOMING CHANGES AT \(id)\nON \(eff) · CURRENT DATA STAYS THE SAME"
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
    @State private var collapsed: Set<String> = []
    /// collapsed cycles per airport, kept while the app is running (resets on relaunch)
    @MainActor private static var memory: [String: Set<String>] = [:]

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
                let isCollapsed = collapsed.contains(group.cycle)
                Section {
                    if !isCollapsed {
                        ForEach(group.changes) { ChangeRow(change: $0).efbRow(top: 3, bottom: 3) }
                    }
                } header: {
                    Button { toggle(group.cycle) } label: {
                        CycleHeader(cycle: group.cycle, changes: group.changes, collapsed: isCollapsed)
                    }
                    .buttonStyle(.plain)
                    .pinnedHeader()
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
            collapsed = Self.memory[id] ?? []
            do { history = try await API.history(id) } catch { self.error = error.localizedDescription }
            loaded = true
        }
        .onChange(of: collapsed) { _, value in Self.memory[id] = value }
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
                Annunciator(text: showFYI ? "FYI on" : "FYI off", color: showFYI ? EFB.text : EFB.faint)
            }
            .buttonStyle(.plain)
            Button {
                withAnimation(.snappy) {
                    let all = Set(groups.map(\.cycle))
                    collapsed = collapsed.isSuperset(of: all) ? [] : all
                }
            } label: {
                Image(systemName: allCollapsed ? "rectangle.expand.vertical" : "rectangle.compress.vertical")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(EFB.dim)
                    .frame(width: 30, height: 26)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(allCollapsed ? "Expand all cycles" : "Collapse all cycles")
        }
    }

    private var allCollapsed: Bool {
        !groups.isEmpty && collapsed.isSuperset(of: groups.map(\.cycle))
    }

    private func toggle(_ cycle: String) {
        withAnimation(.snappy) {
            if collapsed.contains(cycle) { collapsed.remove(cycle) } else { collapsed.insert(cycle) }
        }
    }
}

/// tappable "EFF 10 JUL 2025" header; shows counts when collapsed so you still see what's inside
private struct CycleHeader: View {
    let cycle: String
    let changes: [Change]
    let collapsed: Bool

    private var counts: Counts {
        Counts(action: changes.filter { $0.level == .action }.count,
               ifr: changes.filter { $0.level == .ifr }.count,
               fyi: changes.filter { $0.level == .fyi }.count)
    }

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "chevron.right")
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(EFB.cyan)
                .rotationEffect(.degrees(collapsed ? 0 : 90))
            EFBHeader(text: "Effective \(Cycle.efb(cycle))", color: EFB.text)
            Rectangle().fill(EFB.line).frame(height: 1)
            if collapsed {
                CountAnnunciators(counts: counts, showNoChange: false)
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
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
                    .pinnedHeader()
                }
                .listSectionSeparator(.hidden)
            }
        }
    }
}

/// makes it impossible to mistake upcoming changes for what's in effect today
private struct EffectiveNote: View {
    let fromCycle: String
    let toCycle: String

    private var days: Int { Cycle.daysUntil(toCycle) ?? 0 }
    private var upcoming: Bool { !Cycle.isInEffect(toCycle) }
    private var when: String {
        switch days {
        case ...0: "today at 0901Z"
        case 1: "tomorrow at 0901Z"
        default: "in \(days) days"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Annunciator(text: upcoming ? "Not in effect yet" : "In effect",
                        color: upcoming ? EFB.cyan : EFB.green)
            Text(upcoming
                 ? "These changes take effect \(Cycle.efb(toCycle)) 0901Z (\(when)). Until then, the current value applies: it's the one before the →."
                 : "In effect since \(Cycle.efb(toCycle)) 0901Z. Compared to the previous cycle (\(Cycle.efb(fromCycle))), the value after the → is what applies now.")
                .font(.footnote)
                .foregroundStyle(EFB.text.opacity(0.8))
                .fixedSize(horizontal: false, vertical: true)
        }
        .efbPanel()
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


private extension View {
    /// list section headers stick to the top while scrolling; give them the page background
    /// so the rows underneath don't show through
    func pinnedHeader() -> some View {
        self.padding(.horizontal, 16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(EFB.bg)
            .listRowInsets(EdgeInsets())
    }
}
