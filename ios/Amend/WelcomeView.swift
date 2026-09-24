import SwiftUI

/// First-launch onboarding: what it is, how to read it, set up home + alerts.
/// Shown again from Settings > Show welcome again.
struct WelcomeView: View {
    @Environment(AirportStore.self) private var store
    @AppStorage(SettingsKey.onboarded) private var onboarded = false
    @AppStorage(SettingsKey.notifyEnabled) private var notifyEnabled = false

    @State private var page = 0
    @State private var showingAdd = false
    @State private var showingGuide = false

    private let pages = 3

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                if page < pages - 1 {
                    Button("Skip") { onboarded = true }
                        .font(EFB.mono(13, .semibold))
                        .foregroundStyle(EFB.dim)
                }
            }
            .frame(height: 44)
            .padding(.horizontal)

            TabView(selection: $page) {
                intro.tag(0)
                reading.tag(1)
                setup.tag(2)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))

            footer
        }
        .background(EFB.bg)
        .sheet(isPresented: $showingAdd) { AddAirportView() }
        .sheet(isPresented: $showingGuide) { NavigationStack { GuideView() } }
    }

    // MARK: pages

    private var intro: some View {
        pageLayout(icon: "airplane.departure", title: "AMEND") {
            Text("Every 28 days the FAA publishes a new cycle of airport, airspace and chart data. Tower hours move, runways get renumbered, approaches get amended, and it's easy to miss.")
            Text("Amend compares each cycle to the last one and tells you what changed at your airports, in plain English, up to three weeks before it takes effect.")
        }
    }

    private var reading: some View {
        pageLayout(icon: "list.bullet.rectangle", title: "HOW TO READ IT") {
            chip("ACT", EFB.amber, "Changes how you fly it: tower hours, frequencies, runways, navaids")
            chip("IFR", EFB.cyan, "Approaches, STARs, departures and IFR routes")
            chip("FYI", EFB.dim, "Worth knowing: phone numbers, fees, obstacles, reworded remarks")
            chip("NO CHG", EFB.green, "Nothing changed there this cycle")
            Text("Remarks are the FAA's free-text airport notes. They're translated to plain English, and the original FAA text is always one tap away.")
            Button("Read the full guide") { showingGuide = true }
                .font(EFB.mono(13, .bold))
                .foregroundStyle(EFB.cyan)
        }
    }

    private var setup: some View {
        pageLayout(icon: "house", title: "SET UP") {
            Text("Add your home field first. You'll be notified about any change there, and about action items at your other airports.")

            Button { showingAdd = true } label: {
                setupRow(done: store.home != nil,
                         title: store.home.map { "Home: \($0)" } ?? "Choose home airport",
                         icon: "house.fill")
            }
            .buttonStyle(.plain)

            Button {
                Task {
                    if await NotificationManager.requestPermission() {
                        notifyEnabled = true
                        NotificationManager.scheduleRefresh()
                    }
                }
            } label: {
                setupRow(done: notifyEnabled, title: notifyEnabled ? "Cycle alerts on" : "Turn on cycle alerts",
                         icon: "bell.fill")
            }
            .buttonStyle(.plain)

            Text("NOT FOR NAVIGATION. Always use official FAA publications, NOTAMs and a proper preflight briefing.")
                .font(EFB.mono(10))
                .foregroundStyle(EFB.faint)
        }
    }

    // MARK: pieces

    private var footer: some View {
        VStack(spacing: 16) {
            HStack(spacing: 8) {
                ForEach(0..<pages, id: \.self) { i in
                    Capsule()
                        .fill(i == page ? EFB.cyan : EFB.faint)
                        .frame(width: i == page ? 22 : 8, height: 6)
                }
            }
            .animation(.snappy, value: page)

            Button {
                if page < pages - 1 {
                    withAnimation { page += 1 }
                } else {
                    onboarded = true
                }
            } label: {
                Text(page < pages - 1 ? "NEXT" : "GET STARTED")
                    .font(EFB.mono(15, .bold))
                    .tracking(2)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .foregroundStyle(EFB.bg)
                    .background(EFB.cyan, in: RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding()
    }

    private func pageLayout<Content: View>(icon: String, title: String,
                                     @ViewBuilder _ content: () -> Content) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Image(systemName: icon)
                    .font(.system(size: 40, weight: .semibold))
                    .foregroundStyle(EFB.cyan)
                    .padding(.top, 24)
                Text(title)
                    .font(EFB.mono(24, .bold))
                    .tracking(2)
                    .foregroundStyle(EFB.text)
                VStack(alignment: .leading, spacing: 14) { content() }
                    .font(.body)
                    .foregroundStyle(EFB.text.opacity(0.85))
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, 24)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func chip(_ label: String, _ color: Color, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Annunciator(text: label, color: color).frame(width: 70, alignment: .leading)
            Text(text).font(.subheadline)
        }
    }

    private func setupRow(done: Bool, title: String, icon: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: done ? "checkmark.circle.fill" : icon)
                .foregroundStyle(done ? EFB.green : EFB.cyan)
                .frame(width: 24)
            Text(title.uppercased())
                .font(EFB.mono(14, .bold))
                .foregroundStyle(done ? EFB.green : EFB.text)
            Spacer()
            if !done { Image(systemName: "chevron.right").foregroundStyle(EFB.faint) }
        }
        .efbPanel()
    }
}
