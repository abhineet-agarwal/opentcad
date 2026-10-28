load microrobot_bias
select top cell
expand
extract all
ext2sim labels on
ext2sim
extresist tolerance 10
extresist
ext2spice lvs
ext2spice cthresh 0
ext2spice extresist on
ext2spice -o bias_rc.spice

puts "OPENTCAD_FLOW_DONE"
quit -noprompt
