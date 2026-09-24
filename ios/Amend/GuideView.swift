import SwiftUI

/// What the labels mean. Opened from the (i) on the cycle panel and from Settings.
struct GuideView: View {
    @Environment(\.dismiss) private var dismiss
    var showsDone = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                section("Priority") {
                    tier(.action, "ACT",
                         "Changes how you fly the airport. Tower or Class D hours, frequencies, runways closed, renumbered or restricted, navaids removed or changed, new PPR or noise rules.",
                         "Tower hours changed: 0700-2100 → 0700-0100 local")
                    tier(.ifr, "IFR",
                         "Instrument procedures: approaches amended, added or removed, STARs and departures, preferred IFR routes. Matters most if you fly IFR there.",
                         "Approach ILS OR LOC RWY 04R amended (AMDT 11C)")
                    tier(.fyi, "FYI",
                         "Worth knowing, rarely changes your flight: phone numbers, landing fees, obstacle and marking updates, name changes, reworded remarks.",
                         "Airport phone number changed")
                    tierRow(color: EFB.green, label: "NO CHG",
                            text: "Nothing at this airport changed between the two cycles.")
                }

                section("Remarks") {
                    Text("Remarks are the free-text notes in the FAA Chart Supplement (the old A/FD) for an airport: things like PPR requirements, runway restrictions, wildlife, noise abatement, when services aren't available.")
                        .guideBody()
                    Text("The FAA writes them in contractions (RSCD NOT MNT 2300-0600 M-F). Amend translates them to plain English with AI using a fixed FAA glossary; unknown abbreviations are left as-is instead of guessed. Tap FAA TEXT ▸ on any remark to see the original, and trust the original if they ever disagree.")
                        .guideBody()
                }

                section("Cycles") {
                    Text("The FAA publishes airport and airspace data every 28 days (NASR) and instrument charts on the same schedule (d-TPP). Each cycle has an effective date.")
                        .guideBody()
                    tierRow(color: EFB.cyan, label: "UPCOMING",
                            text: "The next cycle is already published but not in effect yet, so you can see changes before they happen. Great time to check your airports.")
                    tierRow(color: EFB.green, label: "IN EFFECT",
                            text: "The newest cycle is active. Shows what changed compared to the one before it.")
                    Text("History goes back to Aug 2024 for airport data. Chart history starts in fall 2026 because the FAA doesn't keep old chart indexes online.")
                        .guideBody()
                }

                section("Home airport") {
                    Text("Pinned at the top. You get notified about any change there, even FYI, since it's where you fly most. Other airports follow your notification setting.")
                        .guideBody()
                }

                Text("NOT FOR NAVIGATION. Amend is an awareness and study tool. Always use official FAA publications, NOTAMs and a proper preflight briefing.")
                    .font(EFB.mono(10))
                    .foregroundStyle(EFB.faint)
                    .padding(.top, 4)
            }
            .padding()
        }
        .background(EFB.bg)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(EFB.bg, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .principal) {
                Text("GUIDE").font(EFB.mono(15, .bold)).tracking(2).foregroundStyle(EFB.text)
            }
            if showsDone {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
        }
    }

    private func section<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            EFBHeader(text: title)
            content()
        }
        .efbPanel()
    }

    private func tier(_ level: Priority, _ label: String, _ text: String, _ example: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            tierRow(color: level.color, label: label, text: text)
            Text("e.g. " + example)
                .font(EFB.mono(11))
                .foregroundStyle(level.color.opacity(0.8))
                .padding(.leading, 102)
        }
    }

    private func tierRow(color: Color, label: String, text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Annunciator(text: label, color: color)
                .frame(width: 92, alignment: .leading)
            Text(text).guideBody()
        }
    }
}

private extension Text {
    func guideBody() -> some View {
        self.font(.subheadline)
            .foregroundStyle(EFB.text.opacity(0.85))
            .fixedSize(horizontal: false, vertical: true)
    }
}
