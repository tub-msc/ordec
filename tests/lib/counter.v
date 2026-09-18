/* SPDX-FileCopyrightText: 2026 ORDeC contributors
 * SPDX-License-Identifier: Apache-2.0
 */
module counter(
    input wire clk_i,
    input wire rst_ni,
    input wire down_i,
    input wire en_i,
    output reg [7:0] val_o
);

    always @(posedge clk_i, negedge rst_ni) begin
        if(~rst_ni) begin
            val_o <= '0;
        end
        else begin
            if(en_i) begin
                if(down_i) begin
                    val_o <= val_o - 1;
                end
                else begin
                    val_o <= val_o + 1;
                end
            end
        end
    end

endmodule
