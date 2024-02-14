import strax
import numpy as np
import straxen
import logging
from immutabledict import immutabledict

from ...common import pmt_gains
from ...plugin import FuseBasePlugin

export, __all__ = strax.exporter()

logging.basicConfig(handlers=[logging.StreamHandler()])
log = logging.getLogger('fuse.detector_physics.secondary_scintillation')

@export
class SecondaryScintillation(FuseBasePlugin):
    """Plugin to simulate the secondary scintillation process in the gas phase."""
    
    __version__ = "0.2.0"
    
    depends_on = ("drifted_electrons","extracted_electrons" ,"electron_time")
    provides = ("s2_photons", "s2_photons_sum")
    data_kind = {"s2_photons": "individual_electrons",
                 "s2_photons_sum" : "interactions_in_roi"
                }
    
    dtype_photons = [(("Number of photons produced by the extracted electron","n_s2_photons"), np.int32),] + strax.time_fields
    dtype_sum_photons = [(("Sum of all photons produced by electrons originating from the same cluster", "sum_s2_photons"), np.int32),] + strax.time_fields
    
    dtype = dict()
    dtype["s2_photons"] = dtype_photons
    dtype["s2_photons_sum"] = dtype_sum_photons

    save_when = immutabledict(s2_photons=strax.SaveWhen.TARGET,
                              s2_photons_sum=strax.SaveWhen.ALWAYS
                              )
    
    #Config options
    s2_secondary_sc_gain_mc = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=s2_secondary_sc_gain",
        type=(int, float),
        cache=True,
        help='Secondary scintillation gain [PE/e-]',
    )

    pmt_circuit_load_resistor = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=pmt_circuit_load_resistor",
        type=(int, float),
        cache=True,
        help='PMT circuit load resistor [kg m^2/(s^3 A)]',
    )

    digitizer_bits = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=digitizer_bits",
        type=(int, float),
        cache=True,
        help='Number of bits of the digitizer boards',
    )

    digitizer_voltage_range = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=digitizer_voltage_range",
        type=(int, float),
        cache=True,
        help='Voltage range of the digitizer boards [V]',
    )

    se_gain_from_map = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=se_gain_from_map",
        cache=True,
        help='Boolean indication if the secondary scintillation gain is taken from a map',
    )

    p_double_pe_emision = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=p_double_pe_emision",
        type=(int, float),
        cache=True,
        help='Probability of double photo-electron emission',
    )
    
    se_gain_map = straxen.URLConfig(
        default = 'itp_map://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=se_gain_map'
                  '&fmt=json',
        cache=True,
        help='Map of the single electron gain ',
    )
    
    s2_correction_map = straxen.URLConfig(
        default = 'itp_map://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=s2_correction_map'
                  '&fmt=json',
        cache=True,
        help='S2 correction map',
    )
    
    gain_model_mc = straxen.URLConfig(
        default="cmt://to_pe_model?version=ONLINE&run_id=plugin.run_id",
        infer_type=False,
        help='PMT gain model',
    )

    n_top_pmts = straxen.URLConfig(
        type=(int),
        help='Number of PMTs on top array',
    )

    n_tpc_pmts = straxen.URLConfig(
        type=(int),
        help='Number of PMTs in the TPC',
    )

    s2_mean_area_fraction_top = straxen.URLConfig(
        default = "take://resource://"
                  "SIMULATION_CONFIG_FILE.json?&fmt=json"
                  "&take=s2_mean_area_fraction_top",
        type=(int, float),
        cache=True,
        help='Mean S2 area fraction top',
    )
    
    s2_pattern_map = straxen.URLConfig(
        default = 's2_aft_scaling://pattern_map://resource://simulation_config://'
                  'SIMULATION_CONFIG_FILE.json?'
                  '&key=s2_pattern_map'
                  '&fmt=pkl'
                  '&pmt_mask=plugin.pmt_mask'
                  '&s2_mean_area_fraction_top=plugin.s2_mean_area_fraction_top'
                  '&n_tpc_pmts=plugin.n_tpc_pmts'
                  '&n_top_pmts=plugin.n_top_pmts'
                  ,
        cache=True,
        help='S2 pattern map',
    )

    def setup(self):
        super().setup()
        
        self.gains = pmt_gains(self.gain_model_mc,
                               digitizer_voltage_range=self.digitizer_voltage_range,
                               digitizer_bits=self.digitizer_bits,
                               pmt_circuit_load_resistor=self.pmt_circuit_load_resistor
                               )

        self.pmt_mask = np.array(self.gains)
    
    def compute(self, interactions_in_roi, individual_electrons):
        
        #Just apply this to clusters with photons
        mask = interactions_in_roi["n_electron_extracted"] > 0

        if len(interactions_in_roi[mask]) == 0:
            empty_result = np.zeros(len(interactions_in_roi), self.dtype["s2_photons_sum"])
            empty_result["time"] = interactions_in_roi["time"]
            empty_result["endtime"] = interactions_in_roi["endtime"]
            
            return dict(s2_photons=np.zeros(0, self.dtype["s2_photons"]),
                        s2_photons_sum=empty_result)
        
        positions = np.array([interactions_in_roi[mask]["x_obs"], interactions_in_roi[mask]["y_obs"]]).T
        
        sc_gain = self.get_s2_light_yield(positions=positions)
        
        electron_gains = np.repeat(sc_gain, interactions_in_roi[mask]["n_electron_extracted"])
        
        n_photons_per_ele = self.rng.poisson(electron_gains)
        
        electron_indices = np.cumsum(interactions_in_roi[mask]["n_electron_extracted"])
        sum_photons_per_interaction = np.add.reduceat(n_photons_per_ele, np.r_[0, electron_indices[:-1]])
        
        n_photons_per_ele = np.clip(n_photons_per_ele, 0, None)

        reorder_electrons = np.argsort(individual_electrons, order = ["order_index", "time"])
        
        result_photons = np.zeros(len(n_photons_per_ele), dtype = self.dtype["s2_photons"])
        result_photons["n_s2_photons"] = n_photons_per_ele
        result_photons["time"] = individual_electrons["time"][reorder_electrons]
        result_photons["endtime"] = individual_electrons["endtime"][reorder_electrons]
        result_photons = strax.sort_by_time(result_photons)
        
        result_sum_photons = np.zeros(len(interactions_in_roi), dtype = self.dtype["s2_photons_sum"])
        result_sum_photons["sum_s2_photons"][mask] = sum_photons_per_interaction
        result_sum_photons["time"] = interactions_in_roi["time"]
        result_sum_photons["endtime"]= interactions_in_roi["endtime"]

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
            sc_gain *= self.s2_secondary_sc_gain_mc

        # depending on if you use the data driven or mc pattern map for light yield for S2
        # the shape of n_photon_hits will change. Mc needs a squeeze
        if len(sc_gain.shape) != 1:
            sc_gain=np.squeeze(sc_gain, axis=-1)

        # sc gain should has the unit of pe / electron, here we divide 1 + dpe to get nphoton / electron
        sc_gain /= 1 + self.p_double_pe_emision

        # data driven map contains nan, will be set to 0 here
        sc_gain[np.isnan(sc_gain)] = 0
        
        return sc_gain