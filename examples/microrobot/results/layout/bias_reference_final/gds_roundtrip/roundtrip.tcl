gds read ../microrobot_bias.gds
load microrobot_bias
select top cell
expand
box values -10um 0um 100um 60um
drc check
drc catchup
set f [open drc.txt w]
puts $f "DRC_ERRORS [drc list count total]"
puts $f [drc listall why]
close $f
extract all
ext2spice lvs
ext2spice -o bias_lvs.spice

puts "OPENTCAD_FLOW_DONE"
quit -noprompt
