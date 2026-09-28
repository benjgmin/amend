import SwiftUI

struct AirportsView: View {
    @Environment(AirportStore.self) private var store
    @State private var showingAdd = false
    @State private var showingSettings = false
    @State private var showingGuide = false
    @AppStorage(SettingsKey.onboarded) private var onboarded = false

    var body: some View {
        NavigationStack {
            List {
                if let meta = store.meta {
                    CycleStrip(meta: meta) { showingGuide = true }.efbRow(top: 8, bottom: 12)
                }

                // a row, not an overlay: an overlay stays put while pull-to-refresh moves the list,
                // so it slid over the cycle panel
                if store.saved.isEmpty {
                    ContentUnavailableView {
                        Label("No airports", systemImage: "airplane")
                    } description: {
                        Text("Add the airports you fly to. Amend shows what changes at each one every FAA cycle. To make one your home field, open it and tap the house.")
                    } actions: {
                        Button("Add airport") { showingAdd = true }
                            .buttonStyle(.borderedProminent)
                    }
                    .efbRow(top: 24, bottom: 8)
                }

                if let home = store.home {
                    EFBHeader(text: "Home").efbRow(top: 4, bottom: 2)
                    tile(home, isHome: true)
                        .swipeActions { removeButton(home) }
                }

                if !store.others.isEmpty {
                    EFBHeader(text: store.home == nil ? "My airports" : "Watching")
                        .efbRow(top: 12, bottom: 2)
                }
                ForEach(store.others, id: \.self) { id in
                    tile(id, isHome: false)
                        .swipeActions { removeButton(id) }
                }
                .onMove { store.moveOthers(from: $0, to: $1) }

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
                    Button { showingAdd = true } label: { Image(systemName: "plus") }
                        .accessibilityLabel("Add airport")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if let url = watchlistURL {
                        ShareLink(item: url, subject: Text("My airports on Amend"),
                                  message: Text("What's changing at my airports this FAA cycle")) {
                            Image(systemName: "square.and.arrow.up")
                        }
                        .accessibilityLabel("Share watchlist")
                    }
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
            .alert("Couldn't load FAA data", isPresented: .constant(store.errorMessage != nil)) {
                Button("OK") { store.errorMessage = nil }
            } message: {
                Text(store.errorMessage ?? "")
            }
        }
    }

    /// the website shows the same list at amend.watch/list/?w=DAB,VRB,...
    private var watchlistURL: URL? {
        guard !store.saved.isEmpty else { return nil }
        return URL(string: "\(API.base.absoluteString)list/?w=\(store.saved.joined(separator: ","))")
    }

    /// same swipe action everywhere: it takes the airport off your list, it doesn't delete any data
    private func removeButton(_ id: String) -> some View {
        Button(role: .destructive) { store.remove(id) } label: { Label("Remove", systemImage: "minus.circle") }
    }

    /// tile with the chevron inside the panel (the hidden NavigationLink does the navigation)
    private func tile(_ id: String, isHome: Bool) -> some View {
        ZStack {
            NavigationLink(value: id) { EmptyView() }.opacity(0)
            AirportTile(id: id, info: store.info(for: id), counts: store.counts(for: id),
                        indexLoaded: store.index != nil, isHome: isHome)
        }
        .efbRow(top: 3, bottom: 3)
    }
}

private struct CycleStrip: View {
    let meta: Meta
    var onInfo: () -> Void = {}

    private var days: Int? { Cycle.daysUntil(meta.toCycle) }
    /// the site says "upcoming" until its next daily run; trust the clock (changeover is 0901Z)
    private var upcoming: Bool { meta.upcoming && !Cycle.isInEffect(meta.toCycle) }

    private var countdown: String {
        switch days ?? 0 {
        case ...0: "today 0901Z"
        case 1: "tomorrow"
        case let d: "in \(d) days"
        }
    }

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
                    Text(countdown).font(.system(size: 15, weight: .medium)).foregroundStyle(EFB.cyan)
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
