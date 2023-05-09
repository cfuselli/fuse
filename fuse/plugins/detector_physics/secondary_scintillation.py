import strax
import numpy as np
import straxen
from copy import deepcopy
import os
import logging

export, __all__ = strax.exporter()

from ...common import make_map, make_patternmap

logging.basicConfig(handlers=[logging.StreamHandler()])
log = logging.getLogger('fuse.detector_physics.secondary_scintillation')
log.setLevel('WARNING')

#private_files_path = "path/to/private/files"
base_path = os.path.abspath(os.getcwd())
private_files_path = os.path.join("/",*base_path.split("/")[:-2], "private_nt_aux_files")
config = straxen.get_resource(os.path.join(private_files_path, 'sim_files/fax_config_nt_sr0_v4.json') , fmt='json')

@export
@strax.takes_config(
    strax.Option('p_double_pe_emision', default=config["p_double_pe_emision"], track=False, infer_type=False,
                 help="p_double_pe_emision"),
    strax.Option('se_gain_from_map', default=config["se_gain_from_map"], track=False, infer_type=False,
                 help="se_gain_from_map"),
    strax.Option('se_gain_map',
                 default=os.path.join(private_files_path,"strax_files/XENONnT_se_xy_map_v1_mlp.json"),
                 track=False,
                 infer_type=False,
                 help="se_gain_map"),
    strax.Option('s2_correction_map_file',
                 default=os.path.join(private_files_path,"strax_files/XENONnT_s2_xy_map_v4_210503_mlp_3_in_1_iterated.json"),
                 track=False,
                 infer_type=False,
                 help="s2_correction_map"),
    strax.Option('to_pe_file', default=os.path.join(private_files_path,"sim_files/to_pe_nt.npy"), track=False, infer_type=False,
                 help="to_pe file"),
    strax.Option('digitizer_voltage_range', default=config['digitizer_voltage_range'], track=False, infer_type=False,
                 help="digitizer_voltage_range"),
    strax.Option('digitizer_bits', default=config['digitizer_bits'], track=False, infer_type=False,
                 help="digitizer_bits"),
    strax.Option('pmt_circuit_load_resistor', default=config['pmt_circuit_load_resistor'], track=False, infer_type=False,
                 help="pmt_circuit_load_resistor"),
    strax.Option('s2_pattern_map_file',
                 default=os.path.join(private_files_path,"sim_files/XENONnT_s2_xy_patterns_GXe_LCE_corrected_qes_MCv4.3.0_wires.pkl"),
                 track=False,
                 infer_type=False,
                 help="s2_pattern_map"),
    strax.Option('s2_secondary_sc_gain', default=config['s2_secondary_sc_gain'], track=False, infer_type=False,
                 help="s2_secondary_sc_gain"),
    strax.Option('s2_gain_spread', default=0, track=False, infer_type=False,
                 help="s2_gain_spread"),
    strax.Option('debug', default=False, track=False, infer_type=False,
                 help="Show debug informations"),
)
class SecondaryScintillation(strax.Plugin):
    
    __version__ = "0.0.0"
    
    depends_on = ("drifted_electrons","extracted_electrons" ,"electron_time")
    provides = ("s2_photons", "s2_photons_sum")
    data_kind = {"s2_photons": "individual_electrons",
                 "s2_photons_sum" : "electron_cloud"
                }
    
    dtype_photons = [('n_photons', np.int64),] + strax.time_fields
    dtype_sum_photons = [('sum_photons', np.int64),] + strax.time_fields
    
    dtype = dict()
    dtype["s2_photons"] = dtype_photons
    dtype["s2_photons_sum"] = dtype_sum_photons

    #Forbid rechunking
    rechunk_on_save = False
    
    def setup(self):
        
        if self.debug:
            log.setLevel('DEBUG')
            log.debug("Running SecondaryScintillation in debug mode")

        if self.se_gain_from_map:
            self.se_gain_map = make_map(self.se_gain_map, fmt = "json")
        else: 
            if self.s2_correction_map_file:
                self.s2_correction_map = make_map(self.s2_correction_map_file, fmt = 'json')
            else:
                
                to_pe = straxen.get_resource(self.to_pe_file, fmt='npy')
                self.to_pe = to_pe[0][1]

                adc_2_current = (self.digitizer_voltage_range
                        / 2 ** (self.digitizer_bits)
                         / self.pmt_circuit_load_resistor)

                gains = np.divide(adc_2_current,
                                  self.to_pe,
                                  out=np.zeros_like(self.to_pe),
                                  where=self.to_pe != 0)

                self.pmt_mask = np.array(gains) > 0  # Converted from to pe (from cmt by default)

                self.s2_pattern_map = make_patternmap(self.s2_pattern_map_file, fmt='pkl', pmt_mask=self.pmt_mask)
                
                
                s2cmap = deepcopy(self.s2_pattern_map)
                # Lower the LCE by removing contribution from dead PMTs
                # AT: masking is a bit redundant due to PMT mask application in make_patternmap
                s2cmap.data['map'] = np.sum(s2cmap.data['map'][:][:], axis=2, keepdims=True, where=self.pmt_mask)
                # Scale by median value
                s2cmap.data['map'] = s2cmap.data['map'] / np.median(s2cmap.data['map'][s2cmap.data['map'] > 0])
                s2cmap.__init__(s2cmap.data)
                self.s2_correction_map = s2cmap
    
    def compute(self, electron_cloud, individual_electrons ):

        if len(electron_cloud) == 0:
            return dict(s2_photons=np.zeros(0, self.dtype["s2_photons"]),
                        s2_photons_sum=np.zeros(0, self.dtype["s2_photons_sum"]))
        
        positions = np.array([electron_cloud["x"], electron_cloud["y"]]).T
        
        sc_gain = self.get_s2_light_yield(positions=positions)
        
        electron_gains = np.repeat(sc_gain, electron_cloud["n_electron_extracted"])
        
        n_photons_per_ele = np.random.poisson(electron_gains)
        
        if self.s2_gain_spread:
            n_photons_per_ele += np.random.normal(0, self.s2_gain_spread, len(n_photons_per_ele)).astype(np.int64)
        
        sum_photons_per_interaction = [np.sum(x) for x in np.split(n_photons_per_ele, np.cumsum(electron_cloud["n_electron_extracted"]))[:-1]]
        
        n_photons_per_ele[n_photons_per_ele < 0] = 0
        
        result_photons = np.zeros(len(n_photons_per_ele), dtype = self.dtype["s2_photons"])
        result_photons["n_photons"] = n_photons_per_ele
        result_photons["time"] = individual_electrons["time"]
        result_photons["endtime"] = individual_electrons["endtime"]
        
        result_sum_photons = np.zeros(len(sum_photons_per_interaction), dtype = self.dtype["s2_photons_sum"])
        result_sum_photons["sum_photons"] = sum_photons_per_interaction
        result_sum_photons["time"] = electron_cloud["time"]
        result_sum_photons["endtime"] = electron_cloud["endtime"]
        
        return dict(s2_photons=result_photons,
                    s2_photons_sum=result_sum_photons)
        
        
    def get_s2_light_yield(self, positions):
        """Calculate s2 light yield...

        :param positions: 2d array of positions (floats)

        returns array of floats (mean expectation) 
        """

        if self.se_gain_from_map:
            sc_gain = self.se_gain_map(positions)
        else:
            # calculate it from MC pattern map directly if no "se_gain_map" is given
            sc_gain = self.s2_correction_map(positions)
            sc_gain *= self.s2_secondary_sc_gain

        # depending on if you use the data driven or mc pattern map for light yield for S2
        # the shape of n_photon_hits will change. Mc needs a squeeze
        if len(sc_gain.shape) != 1:
            sc_gain=np.squeeze(sc_gain, axis=-1)

        # sc gain should has the unit of pe / electron, here we divide 1 + dpe to get nphoton / electron
        sc_gain /= 1 + self.p_double_pe_emision

        # data driven map contains nan, will be set to 0 here
        sc_gain[np.isnan(sc_gain)] = 0
        
        return sc_gain