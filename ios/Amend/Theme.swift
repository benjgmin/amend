import SwiftUI
import UIKit

/// The app's look, the same as amend.watch: calm neutrals that follow light and dark mode, and colour only
/// where it means something, as on a sectional chart: magenta = action, blue = IFR (and links), grey = FYI,
/// green = nothing changed. The names are older than the colours: `amber` is the action magenta, `cyan` the blue.
enum EFB {
    static let bg = Color(light: 0xF6F8FA, dark: 0x09121C)
    static let panel = Color(light: 0xFFFFFF, dark: 0x0E1926)
    static let panelHi = Color(light: 0xEEF2F6, dark: 0x152233)
    static let line = Color(light: 0xDDE3EA, dark: 0x1F3044)
    static let lineStrong = Color(light: 0xC3CCD7, dark: 0x2E4460)
    static let text = Color(light: 0x0D1B2A, dark: 0xE6EDF5)
    static let dim = Color(light: 0x4B5B6E, dark: 0x9DAEC2)
    static let faint = Color(light: 0x667385, dark: 0x7A8DA4)
    static let amber = Color(light: 0xA3186E, dark: 0xE26BB2)
    static let cyan = Color(light: 0x1A5EA6, dark: 0x7FB2EC)
    static let green = Color(light: 0x2D7A4B, dark: 0x67C08B)
    /// text on a solid colour (the action label)
    static let onColor = Color(light: 0xFFFFFF, dark: 0x09121C)
    /// corners of panels and change rows
    static let radius: CGFloat = 10

    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

extension Color {
    /// a color that switches with the system appearance
    init(light: UInt32, dark: UInt32) {
        self.init(UIColor { traits in
            UIColor(hex: traits.userInterfaceStyle == .dark ? dark : light)
        })
    }
}

private extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255,
                  green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255,
                  alpha: 1)
    }
}

extension Priority {
    var color: Color {
        switch self {
        case .action: EFB.amber
        case .ifr: EFB.cyan
        case .fyi: EFB.dim
        }
    }

    var short: String {
        switch self {
        case .action: "ACT"
        case .ifr: "IFR"
        case .fyi: "FYI"
        }
    }
}

/// small label in capitals, like the site's ("ACT 2", "IN EFFECT"): solid for action, outlined for the rest
struct Annunciator: View {
    let text: String
    let color: Color
    var solid: Bool? = nil           // nil: solid only in the action colour

    var body: some View {
        let filled = solid ?? (color == EFB.amber)
        let edge = filled || !(color == EFB.dim || color == EFB.faint) ? color : EFB.lineStrong
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .tracking(0.6)
            .textCase(.uppercase)
            .lineLimit(1)
            .fixedSize()                 // labels never wrap onto two lines
            .foregroundStyle(filled ? EFB.onColor : color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(filled ? color : Color.clear, in: RoundedRectangle(cornerRadius: 3))
            .overlay(RoundedRectangle(cornerRadius: 3).strokeBorder(edge, lineWidth: 1))
    }
}

/// "ACT 2  IFR 4  FYI 3" or "No change"
struct CountAnnunciators: View {
    let counts: Counts?
    var showNoChange = true

    var body: some View {
        HStack(spacing: 4) {
            if let counts, counts.total > 0 {
                ForEach(Priority.allCases) { level in
                    let n = count(level, counts)
                    if n > 0 { Annunciator(text: "\(level.short) \(n)", color: level.color) }
                }
            } else if showNoChange {
                Annunciator(text: "No change", color: EFB.green)
            }
        }
    }

    private func count(_ level: Priority, _ c: Counts) -> Int {
        switch level {
        case .action: c.action
        case .ifr: c.ifr
        case .fyi: c.fyi
        }
    }
}

/// section title in small capitals, like the site's
struct EFBHeader: View {
    let text: String
    var color: Color = EFB.dim

    var body: some View {
        Text(text)
            .font(.system(size: 12, weight: .semibold))
            .tracking(0.7)
            .textCase(.uppercase)
            .foregroundStyle(color)
    }
}

struct PanelModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(EFB.panel, in: RoundedRectangle(cornerRadius: EFB.radius))
            .overlay(RoundedRectangle(cornerRadius: EFB.radius).stroke(EFB.line, lineWidth: 1))
    }
}

extension View {
    func efbPanel() -> some View { modifier(PanelModifier()) }

    /// plain list row with no system chrome
    func efbRow(top: CGFloat = 4, bottom: CGFloat = 4) -> some View {
        self.listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: top, leading: 16, bottom: bottom, trailing: 16))
    }
}
