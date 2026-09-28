import SwiftUI

struct AirportsView: View {
    @Environment(AirportStore.self) private var store
    @State private var showingAdd = false
    @State private var showingSettings = false
    @State private var showingGuide = false
    /// the list name being typed: a new list (nil id) or a rename
    @State private var naming: Naming?
    @State private var nameText = ""
    @State private var deleting: AirportList?
    @State private var importing = false
    @State private var importText = ""
    @State private var importNote: String?
    @AppStorage(SettingsKey.onboarded) private var onboarded = false

    var body: some View {
        NavigationStack {
            List {
                if let meta = store.meta {
                    CycleStrip(meta: meta) { showingGuide = true }.efbRow(top: 8, bottom: 12)
                    if meta.isStale {
                        StaleBanner(meta: meta).efbRow(top: 0, bottom: 12)
                    }
                    if !store.saved.isEmpty && store.index != nil {
                        ComingUpView(meta: meta)
                    }
                }

                // a row, not an overlay: an overlay stays put while pull-to-refresh moves the list,
                // so it slid over the cycle panel
                if store.saved.isEmpty {
                    ContentUnavailableView {
                        Label("No airports", systemImage: "airplane")
                    } description: {
                        Text("Add the airports you fly to. Amend shows what changes at each one every FAA cycle. To make one your home field, open it and tap the house.")
                    } actions: {
                        Button("Search airports") { showingAdd = true }
                            .buttonStyle(.borderedProminent)
                    }
                    .efbRow(top: 24, bottom: 8)
                }

                if let home = store.home {
                    EFBHeader(text: "Home").efbRow(top: 4, bottom: 2)
                    tile(home, isHome: true)
                        .swipeActions {
                            Button(role: .destructive) { store.setHome(nil) } label: {
                                Label("Unpin", systemImage: "house.slash")
                            }
                        }
                }

                if !store.lists.isEmpty || store.home != nil {
                    listHeader.efbRow(top: 12, bottom: 2)
                }
                if let list = store.activeList {
                    if store.lists.count > 1 {
                        ListTabs(lists: store.lists, active: list.id) { store.useList($0) }
                            .efbRow(top: 2, bottom: 6)
                    }
                    ForEach(list.ids, id: \.self) { id in
                        tile(id, isHome: id == store.home)
                            .swipeActions {
                                // takes it off this list only; it doesn't delete any data
                                Button(role: .destructive) { store.setOnList(id, list.id, false) } label: {
                                    Label("Remove", systemImage: "minus.circle")
                                }
                            }
                    }
                    .onMove { store.move(in: list.id, from: $0, to: $1) }
                    if list.ids.isEmpty {
                        Text("No airports on \(list.name) yet. Tap the magnifying glass, find an airport and tap + to add it.")
                            .font(.subheadline)
                            .foregroundStyle(EFB.dim)
                            .efbPanel()
                            .efbRow(top: 3, bottom: 3)
                    }
                }

                // the site's "Most action items this cycle": the busiest airports nationally, to browse
                if !store.busiest.isEmpty, let meta = store.meta {
                    HStack {
                        EFBHeader(text: "Most action items this cycle")
                        Spacer()
                        Text("\(meta.changedAirports.formatted()) airports \(Cycle.isInEffect(meta.toCycle) ? "changed" : "change")")
                            .font(.system(size: 12.5))
                            .foregroundStyle(EFB.faint)
                    }
                    .efbRow(top: 20, bottom: 2)
                    ForEach(store.busiest, id: \.self) { id in
                        ZStack {
                            NavigationLink(value: id) { EmptyView() }.opacity(0)
                            BusyTile(id: id, info: store.info(for: id), counts: store.counts(for: id))
                        }
                        .efbRow(top: 3, bottom: 3)
                    }
                }

                Text("Not for navigation. Always check official FAA publications and NOTAMs.")
                    .font(.footnote)
                    .foregroundStyle(EFB.faint)
                    .efbRow(top: 20, bottom: 20)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(EFB.bg)
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(EFB.bg, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 7) {
                        Image("Logo")
                            .resizable()
                            .frame(width: 22, height: 22)
                        Text("amend")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(EFB.text)
                    }
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("Amend")
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button { showingSettings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel("Settings")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showingAdd = true } label: { Image(systemName: "magnifyingglass") }
                        .accessibilityLabel("Search airports")
                }
            }
            .navigationDestination(for: String.self) { id in
                AirportDetailView(id: id)
            }
            .sheet(isPresented: $showingAdd) { AddAirportView() }
            .sheet(isPresented: $showingSettings) { SettingsView() }
            .sheet(isPresented: $showingGuide) { NavigationStack { GuideView() } }
            .fullScreenCover(isPresented: Binding(get: { !onboarded }, set: { onboarded = !$0 })) {
                WelcomeView()
            }
            .refreshable { await store.refresh() }
            .task { await store.refresh() }
            .alert(naming?.title ?? "", isPresented: Binding(get: { naming != nil }, set: { if !$0 { naming = nil } })) {
                TextField("Name, e.g. Club SVFR or Bahamas trip", text: $nameText)
                Button(naming?.action ?? "Save") { saveName() }
                Button("Cancel", role: .cancel) { naming = nil }
            }
            .confirmationDialog("Delete \u{201C}\(deleting?.name ?? "")\u{201D}?",
                                isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                                titleVisibility: .visible) {
                Button("Delete list", role: .destructive) {
                    if let deleting { store.deleteList(deleting.id) }
                    deleting = nil
                }
            } message: {
                Text("This can't be undone. The airports stay on your other lists.")
            }
            .alert("Open a shared list", isPresented: $importing) {
                TextField("amend.watch/list link or airport IDs", text: $importText)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Save") { Task { await importList() } }
                Button("Cancel", role: .cancel) { }
            } message: {
                Text("Paste a list link someone shared from amend.watch or this app, or type airport IDs.")
            }
            .alert(importNote ?? "", isPresented: Binding(get: { importNote != nil }, set: { if !$0 { importNote = nil } })) {
                Button("OK") { importNote = nil }
            }
            .alert("Couldn't load FAA data", isPresented: .constant(store.errorMessage != nil)) {
                Button("OK") { store.errorMessage = nil }
            } message: {
                Text(store.errorMessage ?? "")
            }
        }
    }

    /// "Club SVFR · 4" with what you can do to the list in use; "Your lists" with more than one
    private var listHeader: some View {
        let list = store.activeList
        return HStack {
            EFBHeader(text: store.lists.count == 1 ? list.map { "\($0.name) · \($0.ids.count)" } ?? "Your lists" : "Your lists")
            Spacer()
            Menu {
                if let list {
                    if let url = list.shareURL, !list.ids.isEmpty {
                        ShareLink(item: url, subject: Text("\(list.name) on Amend"),
                                  message: Text("What's changing at these airports this FAA cycle")) {
                            Label("Share \(list.name)", systemImage: "square.and.arrow.up")
                        }
                    }
                    Button { startNaming(.rename(list.id), list.name) } label: {
                        Label("Rename \(list.name)", systemImage: "pencil")
                    }
                }
                Button { startNaming(.new, "") } label: { Label("New list", systemImage: "plus") }
                Button {
                    importText = ""
                    importing = true
                } label: { Label("Open a shared list", systemImage: "link") }
                if let list {
                    Button(role: .destructive) { deleting = list } label: {
                        Label("Delete \(list.name)", systemImage: "trash")
                    }
                }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.system(size: 17))
                    .frame(width: 36, height: 28)
            }
            .accessibilityLabel("List options")
        }
    }

    /// saves a shared list, or switches to it if you already have the same airports
    private func importList() async {
        do {
            let shared = try await SharedList.read(importText)
            if let have = store.sameList(shared.ids, name: shared.name) {
                store.useList(have.id)
                importNote = "You already have these airports as \u{201C}\(have.name)\u{201D}."
            } else {
                let list = store.createList(shared.name, ids: shared.ids)
                importNote = "Saved \u{201C}\(list.name)\u{201D} with \(list.ids.count) airport\(list.ids.count == 1 ? "" : "s")."
            }
        } catch {
            importNote = error.localizedDescription
        }
    }

    private func startNaming(_ n: Naming, _ text: String) {
        nameText = text
        naming = n
    }

    private func saveName() {
        let name = nameText.trimmingCharacters(in: .whitespacesAndNewlines)
        defer { naming = nil }
        guard !name.isEmpty, let naming else { return }
        switch naming {
        case .new: store.createList(name)
        case .rename(let id): store.renameList(id, to: name)
        }
    }

    /// tile with the chevron inside the panel (the hidden NavigationLink does the navigation)
    private func tile(_ id: String, isHome: Bool) -> some View {
        ZStack {
            NavigationLink(value: id) { EmptyView() }.opacity(0)
            AirportTile(id: id, info: store.info(for: id), counts: store.counts(for: id),
                        indexLoaded: store.index != nil, isHome: isHome, newCount: store.newCount(id))
        }
        .efbRow(top: 3, bottom: 3)
    }
}

private struct CycleStrip: View {
    let meta: Meta
    var onInfo: () -> Void = {}

    /// the site says "upcoming" until its next daily run; trust the clock (changeover is 0901Z)
    private var upcoming: Bool { meta.upcoming && !Cycle.isInEffect(meta.toCycle) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                EFBHeader(text: "NASR cycle")
                Button(action: onInfo) {
                    Image(systemName: "info.circle")
                        .font(.system(size: 13))
                        .foregroundStyle(EFB.dim)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("How Amend works")
                Spacer()
                Annunciator(text: upcoming ? "Upcoming" : "In effect", color: upcoming ? EFB.cyan : EFB.green)
            }

            if upcoming {
                label("Next cycle takes effect 0901Z")
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(Cycle.efb(meta.toCycle)).font(.system(size: 28, weight: .semibold)).foregroundStyle(EFB.text)
                    if let t = Cycle.effectiveInstant(meta.toCycle) {
                        Countdown(to: t).font(.system(size: 15, weight: .medium)).foregroundStyle(EFB.cyan)
                    }
                }
                detail("\(meta.changedAirports) airports change on this date")
                Text("Changes below aren't in effect yet.")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(EFB.cyan)
                Rectangle().fill(EFB.line).frame(height: 1).padding(.vertical, 2)
                detail("In effect now: \(Cycle.efbShort(meta.fromCycle)) – \(Cycle.efb(meta.toCycle)) 0901Z")
            } else {
                label("Current cycle in effect (0901Z to 0901Z)")
                Text("\(Cycle.efbShort(meta.toCycle)) – \(Cycle.efb(Cycle.shift(meta.toCycle, days: 28)))")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(EFB.text)
                detail("\(meta.changedAirports) airports changed since \(Cycle.efb(meta.fromCycle))")
                if let next = Cycle.effectiveInstant(Cycle.shift(meta.toCycle, days: 28)) {
                    HStack(spacing: 4) {
                        Text("Next cycle")
                        Countdown(to: next)
                    }
                    .font(.system(size: 13))
                    .foregroundStyle(EFB.dim)
                }
            }
        }
        .efbPanel()
    }

    private func label(_ text: String) -> some View {
        Text(text).font(.system(size: 12.5)).foregroundStyle(EFB.dim)
    }

    private func detail(_ text: String) -> some View {
        Text(text).font(.system(size: 13)).foregroundStyle(EFB.dim)
    }
}

private struct AirportTile: View {
    let id: String
    let info: AirportInfo?
    let counts: Counts?
    let indexLoaded: Bool
    let isHome: Bool
    var newCount = 0

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(id)
                        .font(EFB.mono(20, .semibold))
                        .foregroundStyle(EFB.text)
                    if let icao = info?.icao, icao != id {
                        Text(icao).font(.system(size: 13)).foregroundStyle(EFB.faint)
                    }
                    if isHome {
                        Image(systemName: "house.fill")
                            .font(.system(size: 11))
                            .foregroundStyle(EFB.cyan)
                    }
                }
                if let info {
                    Text(info.name)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(EFB.text.opacity(0.85))
                        .lineLimit(1)
                    if !info.location.isEmpty {
                        Text(info.location)
                            .font(.system(size: 13))
                            .foregroundStyle(EFB.dim)
                    }
                }
            }
            Spacer(minLength: 8)
            if newCount > 0 {
                NewPill(count: newCount)
            }
            if indexLoaded {
                CountAnnunciators(counts: counts)
            }
            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(EFB.faint)
        }
        .efbPanel()
        .overlay(RoundedRectangle(cornerRadius: EFB.radius)
            .stroke(isHome ? EFB.cyan.opacity(0.5) : Color.clear, lineWidth: 1))
    }
}

/// one of the busiest airports this cycle: id, where it is, its counts, and its top change
private struct BusyTile: View {
    let id: String
    let info: AirportInfo?
    let counts: Counts?
    @State private var top: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(id).font(EFB.mono(16, .semibold)).foregroundStyle(EFB.text)
                Text([info?.name, info?.location].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.system(size: 13))
                    .foregroundStyle(EFB.dim)
                    .lineLimit(1)
                Spacer(minLength: 4)
            }
            CountAnnunciators(counts: counts)
            if let top {
                Text(top)
                    .font(.system(size: 14))
                    .foregroundStyle(EFB.text.opacity(0.85))
                    .lineLimit(2)
            }
        }
        .efbPanel()
        .task(id: id) {
            // the first action item (or the first change), like the site's cards
            guard top == nil, let data = try? await API.latest(id) else { return }
            let first = data.changes.first { $0.level == .action } ?? data.changes.first
            top = first.map { c in
                let s = c.summary.replacingOccurrences(of: " -> ", with: " → ")
                return s.prefix(1).uppercased() + s.dropFirst()
            }
        }
    }
}

private enum Naming: Equatable {
    case new, rename(String)
    var title: String { self == .new ? "New list" : "Rename list" }
    var action: String { self == .new ? "Create" : "Save" }
}

/// one button per list, like the site's tabs; the one in use is filled
private struct ListTabs: View {
    let lists: [AirportList]
    let active: String
    let pick: (String) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(lists) { l in
                    let on = l.id == active
                    Button { pick(l.id) } label: {
                        HStack(spacing: 6) {
                            Text(l.name).lineLimit(1)
                            Text("\(l.ids.count)").foregroundStyle(on ? EFB.bg.opacity(0.75) : EFB.faint)
                        }
                        .font(.system(size: 13.5, weight: .semibold))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .foregroundStyle(on ? EFB.bg : EFB.dim)
                        .background(on ? EFB.text : EFB.panelHi, in: RoundedRectangle(cornerRadius: 8))
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(on ? .isSelected : [])
                }
            }
        }
    }
}
