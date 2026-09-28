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
                Text(id).font(EFB.mono(16, .semibold)).foregroundStyle(EFB.text)
            }
            ToolbarItem(placement: .topBarTrailing) {
                // the same page on amend.watch (airports with no changes on record get the site's "no changes" page)
                if let url = URL(string: "\(API.base.absoluteString)\(id)/") {
                    ShareLink(item: url, subject: Text("\(id) on Amend"),
                              message: Text("What's changing at \(id) this FAA cycle")) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .accessibilityLabel("Share \(id)")
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    if store.isSaved(id) { store.remove(id) } else { store.add(id) }
                } label: {
                    Image(systemName: store.isSaved(id) ? "checkmark.circle.fill" : "plus.circle")
                }
                .accessibilityLabel(store.isSaved(id) ? "Remove from my airports" : "Add to my airports")
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
                    Text(icao).font(.system(size: 15)).foregroundStyle(EFB.faint)
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

    /// "Upcoming" while the newest cycle isn't in effect yet, "Latest" once it is
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
            if let meta = store.meta, meta.isStale {
                StaleBanner(meta: meta).efbRow(top: 12, bottom: 0)
            }
            if let data {
                EffectiveNote(fromCycle: data.fromCycle, toCycle: data.toCycle)
                    .efbRow(top: 12, bottom: 6)
                ChangeSections(changes: data.changes, cycle: data.toCycle)
            } else if loaded && error == nil {
                // a row, not an overlay, so the sources below it stay readable
                NoChangesView(text: noChangesText)
                    .frame(maxWidth: .infinity)
                    .efbRow(top: 48, bottom: 36)
            }
            if loaded && error == nil {
                SourcesPanel(id: id, cycle: store.meta?.toCycle ?? data?.toCycle)
                    .efbRow(top: 16, bottom: 24)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .overlay {
            if let error {
                ContentUnavailableView("Couldn't load", systemImage: "wifi.exclamationmark",
                                       description: Text(error))
            } else if !loaded {
                ProgressView()
            }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    /// talk about the new cycle, not the date range (things did change on the older date)
    private var noChangesText: String {
        guard let meta = store.meta else { return "No changes at \(id) this cycle" }
        let eff = Cycle.efb(meta.toCycle)
        return Cycle.isInEffect(meta.toCycle)
            ? "Nothing changed at \(id)\nin the \(eff) cycle"
            : "No upcoming changes at \(id)\non \(eff) · current data stays the same"
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
    @Environment(AirportStore.self) private var store

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
        // once the newest cycle is in effect it's added to history too, but it's already the list on the
        // first tab (made with today's rules, the one to trust), so history starts with the cycle before it
        let shown = store.meta?.toCycle
        let entries = history.entries.filter { e in
            guard let c = e.cycle, c != shown else { return false }
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
                        ForEach(group.changes) { ChangeRow(change: $0, cycle: group.cycle).efbRow(top: 3, bottom: 3) }
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
            } else if loaded && nothingOnRecord {
                NoChangesView(text: "No changes on record at \(id)\nsince Aug 2024")
            } else if loaded && groups.isEmpty {
                NoChangesView(text: "Nothing in this range\nTry a longer range or turn on FYI",
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
                        .font(.system(size: 13, weight: .semibold))
                        .frame(minWidth: 36)
                        .padding(.vertical, 6)
                        .foregroundStyle(since == s ? EFB.bg : EFB.dim)
                        .background(since == s ? EFB.text : EFB.panelHi, in: RoundedRectangle(cornerRadius: 8))
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

    /// no history file, or only the cycle already shown on the first tab
    private var nothingOnRecord: Bool {
        guard let history else { return true }
        return history.entries.allSatisfy { $0.cycle == store.meta?.toCycle }
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
    var cycle: String? = nil

    var body: some View {
        ForEach(Priority.allCases) { level in
            let group = changes.filter { $0.level == level }
            if !group.isEmpty {
                Section {
                    ForEach(group) { ChangeRow(change: $0, cycle: cycle).efbRow(top: 3, bottom: 3) }
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

/// the FAA publications Amend reads, to check a change against (the same box as on amend.watch)
private struct SourcesPanel: View {
    let id: String
    let cycle: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EFBHeader(text: "Check the official source").padding(.bottom, 6)
            row("Chart Supplement (search \(id))", FAALinks.supplement)
            row("Approach plates (d-TPP)", FAALinks.dtpp)
            row("NOTAMs", FAALinks.notams)
            if let cycle, let url = FAALinks.nasr(cycle) {
                row("NASR data, \(Cycle.efb(cycle))", url)
            }
            Text("Amend reads these FAA files. If they ever disagree, the FAA is right.")
                .font(.footnote)
                .foregroundStyle(EFB.dim)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 10)
            if let url = FAALinks.report(id) {
                Link("Report a wrong change", destination: url)
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(EFB.cyan)
                    .buttonStyle(.borderless)
                    .padding(.top, 4)
            }
        }
        .efbPanel()
    }

    private func row(_ title: String, _ url: URL) -> some View {
        Link(destination: url) {
            HStack {
                Text(title).font(.system(size: 14.5)).foregroundStyle(EFB.text)
                Spacer()
                Image(systemName: "arrow.up.right").font(.system(size: 12, weight: .semibold)).foregroundStyle(EFB.faint)
            }
            .padding(.vertical, 9)
            .overlay(alignment: .bottom) { Rectangle().fill(EFB.line).frame(height: 1) }
            .contentShape(Rectangle())
        }
        .buttonStyle(.borderless)   // several links share one list row; each is its own tap target
    }
}

private struct NoChangesView: View {
    let text: String
    var color: Color = EFB.green

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "checkmark.circle").font(.system(size: 34)).foregroundStyle(color)
            Text(text)
                .font(.system(size: 14, weight: .medium))
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
