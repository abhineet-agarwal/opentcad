# Absolute ruleset qualification fixes this PDK generator under Tcl 9.
# Only an in-memory script copy is changed; no device rules/decks are altered.
set fd [open {/usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tcl} r]
set pdk_text [read $fd]
close $fd
uplevel #0 [string map [list {$sky130::ruleset} {$::sky130::ruleset}] $pdk_text]
random seed 1729
load bias_cells
set specs {{Xb1 nfet_01v8 0.5 8 10 10} {Xmirror nfet_01v8 0.5 8 25 10} {Xb2 nfet_01v8 0.5 8 40 10} {Xb3 nfet_01v8 0.5 8 55 10} {Xpdiode pfet_01v8 1 8 70 10} {Xcbiasn cap_mim_m3_1 7 7 25 30} {Xcbiasp cap_mim_m3_1 7 7 55 30}}
foreach spec $specs {
    lassign $spec name dev w l x y
    box values ${x}um ${y}um ${x}um ${y}um
    if {[string match *fet* $dev]} {
        magic::gencell sky130::sky130_fd_pr__$dev $name w $w l $l viagb 100
    } else {
        magic::gencell sky130::sky130_fd_pr__$dev $name w $w l $l
    }
}
select top cell
expand
save bias_cells
foreach cell [cellname list children bias_cells] {
    load $cell
    save $cell
}
load bias_cells

puts "OPENTCAD_FLOW_DONE"
quit -noprompt
