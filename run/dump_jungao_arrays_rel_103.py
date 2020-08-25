import os
from lfv_pdnn.make_array.make_array import dump_flat_ntuple_individual

# Constants
# 'Pt_ll', 'Eta_ll', 'Phi_ll', 'DR_ll' not available now 
ntuple_name = "Emutau"
feature_list = [
  'M_ll', 'ele_pt', 'ele_eta', 'ele_phi', 'ele_isTight', 'ele_C',
  'mu_pt', 'mu_eta', 'mu_phi', 'mu_isTight', 'mu_C',
  'tau_pt', 'tau_eta', 'tau_phi', 'tau_isTight', 'tau_C', 
  'Pt_ll', 'Eta_ll', 'Phi_ll', 'DPhi_ll', 'DR_ll',
  'met', 'met_eta', 'met_phi',
  'njets', 'nbjets', 'NTauLoose', 'NTauTight',
  'emu', 'etau', 'mutau', 'weight', 'NormSF','nbjetsDL1r77']
bkg_names = ["Diboson_mc", "Top_mc", "Wjets_mc", "LMass_mc"]
sig_names = ["RPV500", "RPV700", "RPV1000", "RPV1500", "RPV2000"]

# Set path in docker
ntup_dir = os.path.join(os.curdir,"../data/merged")
arrays_dir = os.path.join(os.curdir,"../data/arrays/rel_2")
if not os.path.exists(arrays_dir):
  os.makedirs(arrays_dir)

for camp in ["MC16a", "MC16d", "MC16e"]:
  # Dump bkg
  for bkg_name in bkg_names:
    root_path = ntup_dir + "/" + camp + "/{}.root".format(bkg_name)
    dump_flat_ntuple_individual(root_path, ntuple_name, feature_list,
      arrays_dir + "/" + camp, "{}".format(bkg_name),
      use_lower_var_name=False)
  # Dump sig
  for sig_name in sig_names:
    root_path = ntup_dir + "/" + camp + "/{}.root".format(sig_name)
    dump_flat_ntuple_individual(root_path, ntuple_name, feature_list,
      arrays_dir + "/" + camp, "{}".format(sig_name),
      use_lower_var_name=False)
  # Dump data
  # root_path = ntup_dir + "/" + camp + "/data.root"
  # dump_flat_ntuple_individual(root_path, ntuple_name, feature_list,
  #   arrays_dir + "/" + camp, "data_all", use_lower_var_name=False)
