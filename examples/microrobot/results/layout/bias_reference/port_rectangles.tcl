load microrobot_bias
box values -0.2um 44.800um 0.2um 45.200um
findlabel vss
setlabel box
box values -0.2um 46.000um 0.2um 46.400um
findlabel vdd
setlabel box
box values -0.2um 47.200um 0.2um 47.600um
findlabel bias_n
setlabel box
box values -0.2um 48.400um 0.2um 48.800um
findlabel bias_p
setlabel box
save microrobot_bias
gds write microrobot_bias.gds
puts "OPENTCAD_FLOW_DONE"
quit -noprompt
